import os
import re
import uuid
import json
import time
import asyncio
import logging
from datetime import datetime
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import ffmpeg
from bot.config import DOWNLOAD_PATH, MAX_FILE_SIZE
import subprocess
import tempfile
import shutil
from pathlib import Path
import base64

logger = logging.getLogger(__name__)

# Create download directory if it doesn't exist
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

# Regex pattern for YT-DLP supported URLs
URL_PATTERN = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'

def is_valid_url(url):
    """Check if URL is valid for YT-DLP"""
    return bool(re.match(URL_PATTERN, url))

async def _write_temp_cookiefile(cookies_content):
    """Write admin global cookies to a temp file for yt-dlp"""
    if not cookies_content:
        return None
    try:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir=DOWNLOAD_PATH)
        tmp.write(cookies_content)
        tmp.close()
        return tmp.name
    except Exception as e:
        logger.error(f"Error writing temp cookie file: {e}")
        return None

async def get_video_info(url, cookies_content=None):
    """Get video information using YT-DLP"""
    cookie_file = await _write_temp_cookiefile(cookies_content)
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'format': 'best',
        'writeinfojson': True,
        'noplaylist': True,
    }
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    video_id = str(uuid.uuid4())
    info_json = os.path.join(DOWNLOAD_PATH, f"{video_id}.info.json")
    
    try:
        # Run in executor to prevent blocking
        def extract_info():
            with YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        info = await asyncio.get_event_loop().run_in_executor(None, extract_info)
        
        with open(info_json, 'w') as f:
            json.dump(info, f)
        
        # Get available formats
        formats = []
        for f in info.get('formats', []):
            if f.get('resolution') != 'audio only':
                format_id = f.get('format_id')
                resolution = f.get('resolution', 'Unknown')
                ext = f.get('ext', 'mp4')
                filesize = f.get('filesize')
                
                if filesize:
                    filesize_mb = round(filesize / (1024 * 1024), 2)
                    size_str = f"{filesize_mb} MB"
                else:
                    size_str = "Unknown"
                
                formats.append({
                    'format_id': format_id,
                    'resolution': resolution,
                    'ext': ext,
                    'filesize': filesize,
                    'size_str': size_str,
                    'format_note': f.get('format_note', '')
                })
        
        # Add best format option
        formats.append({
            'format_id': 'bestvideo+bestaudio/best',  # Changed this to include fallback to 'best'
            'resolution': 'Best Quality',
            'ext': 'mp4',
            'filesize': None,
            'size_str': 'Variable',
            'format_note': 'Best quality'
        })
            
        return {
            'video_id': video_id,
            'title': info.get('title', 'Unknown Title'),
            'uploader': info.get('uploader', 'Unknown Uploader'),
            'duration': info.get('duration'),
            'formats': formats,
            'thumbnail': info.get('thumbnail'),
            'description': info.get('description', '')
        }
    except DownloadError as e:
        logger.error(f"Error getting video info: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_video_info: {e}")
        return None
    finally:
        if os.path.exists(info_json):
            os.remove(info_json)
        if cookie_file and os.path.exists(cookie_file):
            try: os.remove(cookie_file)
            except: pass

async def download_video(url, format_id, progress_callback=None, cancel_event=None, cookies_content=None):
    """Download video using YT-DLP with non-blocking progress updates"""
    video_id = str(uuid.uuid4())
    output_path = os.path.join(DOWNLOAD_PATH, f"{video_id}.%(ext)s")
    
    async def _download():
        # If format is the best format option, use a more robust format string
        if format_id == 'bestvideo+bestaudio':
            format_id_to_use = 'bestvideo+bestaudio/best'
        else:
            format_id_to_use = format_id
            
        cookie_file = await _write_temp_cookiefile(cookies_content)
        ydl_opts = {
            'format': format_id_to_use,
            'outtmpl': output_path,
            'progress_hooks': [],
            'noplaylist': True,
            'quiet': False,
            'no_warnings': True,
            'continuedl': True,
            'retries': 30,
            'fragment_retries': 30,
            'ignoreerrors': True,
            'merge_output_format': 'mp4'
        }
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file
        
        try:
            def do_download():
                with YoutubeDL(ydl_opts) as ydl:
                    if cancel_event and cancel_event.is_set():
                        raise Exception("Download cancelled by user")
                    info = ydl.extract_info(url, download=True)
                    return info
            
            # Run the blocking download in a thread pool
            info = await asyncio.get_event_loop().run_in_executor(None, do_download)
            
            if cancel_event and cancel_event.is_set():
                raise Exception("Download cancelled by user")
            
            # Handle the case where info is None
            if info is None:
                logger.error("Download completed but info is None")
                # Try to find the file that was created
                possible_files = [
                    f for f in os.listdir(DOWNLOAD_PATH) 
                    if f.startswith(video_id) and os.path.isfile(os.path.join(DOWNLOAD_PATH, f))
                ]
                
                if possible_files:
                    file_path = os.path.join(DOWNLOAD_PATH, possible_files[0])
                    logger.info(f"Found downloaded file despite None info: {file_path}")
                    return {
                        'success': True,
                        'file_path': file_path,
                        'title': 'Unknown Title',
                        'uploader': 'Unknown Uploader',
                        'duration': None,
                        'format': format_id_to_use,
                        'filesize': os.path.getsize(file_path),
                        'video_id': video_id
                    }
                else:
                    return {'success': False, 'error': 'Failed to download video (info is None)'}
            
            try:
                file_path = YoutubeDL(ydl_opts).prepare_filename(info)
                
                # Sometimes the extension is not properly determined for merged formats
                if not os.path.exists(file_path):
                    # Try to find the actual file with the video_id prefix
                    possible_files = [
                        f for f in os.listdir(DOWNLOAD_PATH) 
                        if f.startswith(video_id) and os.path.isfile(os.path.join(DOWNLOAD_PATH, f))
                    ]
                    if possible_files:
                        file_path = os.path.join(DOWNLOAD_PATH, possible_files[0])
                        logger.info(f"Using alternative file path: {file_path}")
                
            except Exception as e:
                logger.error(f"Error preparing filename: {e}")
                # Try to find the file that was created
                possible_files = [
                    f for f in os.listdir(DOWNLOAD_PATH) 
                    if f.startswith(video_id) and os.path.isfile(os.path.join(DOWNLOAD_PATH, f))
                ]
                
                if possible_files:
                    file_path = os.path.join(DOWNLOAD_PATH, possible_files[0])
                    logger.info(f"Found file despite filename preparation error: {file_path}")
                else:
                    return {'success': False, 'error': f'Error preparing filename: {e}'}
            
            if os.path.exists(file_path):
                return {
                    'success': True,
                    'file_path': file_path,
                    'title': info.get('title', 'Unknown Title'),
                    'uploader': info.get('uploader', 'Unknown Uploader'),
                    'duration': info.get('duration'),
                    'format': info.get('format'),
                    'filesize': os.path.getsize(file_path),
                    'video_id': video_id
                }
            else:
                return {'success': False, 'error': 'File not found after download'}
                
        except Exception as e:
            logger.error(f"Error downloading video: {e}")
            return {'success': False, 'error': str(e)}
    
    return await _download()

async def split_file(file_path, max_size=MAX_FILE_SIZE):
    """Split file into chunks of max_size"""
    try:
        # Check if file exists and is not None
        if file_path is None or not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return []
            
        file_size = os.path.getsize(file_path)
        if file_size <= max_size:
            return [file_path]
        
        file_name, ext = os.path.splitext(file_path)
        num_parts = (file_size // max_size) + (1 if file_size % max_size else 0)
        
        try:
            # Run ffprobe in executor
            probe = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ffmpeg.probe(file_path)
            )
            
            duration = float(probe['format']['duration'])
        except Exception as e:
            logger.error(f"Error probing file with ffmpeg, falling back to file-based split: {e}")
            # If ffprobe fails, we can't split by duration, just return the original file
            return [file_path]
            
        part_duration = duration / num_parts
        split_files = []
        
        for i in range(num_parts):
            start_time = i * part_duration
            output_file = f"{file_name}_part{i+1}{ext}"
            
            # Run ffmpeg in executor
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: (
                        ffmpeg
                        .input(file_path, ss=start_time, t=part_duration)
                        .output(output_file, c='copy')
                        .overwrite_output()
                        .run(quiet=True)
                    )
                )
                
                if os.path.exists(output_file):
                    split_files.append(output_file)
            except Exception as e:
                logger.error(f"Error splitting file part {i+1}: {e}")
        
        # If splitting didn't produce any files, return the original
        if not split_files:
            return [file_path]
            
        return split_files
    except Exception as e:
        logger.error(f"Error splitting file: {e}")
        return [file_path] if file_path and os.path.exists(file_path) else []


async def get_video_metadata(video_path):
    """Get comprehensive video metadata using direct ffprobe command"""
    try:
        # Use direct subprocess for more control over ffprobe output
        cmd = [
            'ffprobe', 
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,duration,codec_name,bit_rate,avg_frame_rate:format=duration,bit_rate',
            '-of', 'json',
            video_path
        ]
        
        # Run ffprobe asynchronously
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"ffprobe error: {stderr.decode()}")
            return None
        
        data = json.loads(stdout.decode())
        return process_ffprobe_data(data)
    except Exception as e:
        logger.error(f"Error in get_video_metadata: {e}")
        return None

def process_ffprobe_data(data):
    """Process ffprobe output into standardized metadata format"""
    metadata = {'has_video': False, 'duration': 0, 'width': 0, 'height': 0}
    
    # Extract video stream information
    video_stream = next((stream for stream in data.get('streams', []) 
                        if stream.get('codec_type') == 'video'), None)
    
    if video_stream:
        metadata['has_video'] = True
        metadata['codec_name'] = video_stream.get('codec_name', 'unknown')
        metadata['width'] = int(video_stream.get('width', 0))
        metadata['height'] = int(video_stream.get('height', 0))
        
        # Get duration with fallbacks
        if 'duration' in video_stream:
            metadata['duration'] = float(video_stream.get('duration', 0))
        elif 'format' in data and 'duration' in data['format']:
            metadata['duration'] = float(data['format'].get('duration', 0))
            
        # Get frame rate
        if 'avg_frame_rate' in video_stream:
            try:
                num, den = video_stream['avg_frame_rate'].split('/')
                metadata['frame_rate'] = float(num) / float(den) if float(den) > 0 else 0
            except (ValueError, ZeroDivisionError):
                metadata['frame_rate'] = 0
                
        # Get bitrate
        if 'bit_rate' in video_stream:
            metadata['bit_rate'] = int(video_stream.get('bit_rate', 0))
        elif 'format' in data and 'bit_rate' in data['format']:
            metadata['bit_rate'] = int(data['format'].get('bit_rate', 0))
            
    return metadata

async def extract_frame_with_ffmpeg(video_path, output_path, metadata, position_percent, width, quality):
    """Extract a frame using direct ffmpeg command at the specified position"""
    try:
        # Calculate position based on metadata
        duration = metadata.get('duration', 10)
        if duration <= 0:
            duration = 10  # Fallback value
            
        safe_duration = max(0.5, min(duration * 0.95, duration - 0.5))
        position = max(1, min(safe_duration * position_percent, safe_duration))
        
        # Calculate height while maintaining aspect ratio
        height_param = ""
        if metadata.get('width') and metadata.get('height') and metadata.get('width') > 0:
            height = int(width * metadata.get('height') / metadata.get('width'))
            height_param = f":{height}"
        
        # First try fast seeking (accurate enough for most cases)
        cmd = [
            'ffmpeg',
            '-ss', str(position),
            '-i', video_path,
            '-vframes', '1',
            '-vf', f'scale={width}{height_param}',
            '-q:v', str(min(31, max(1, int(31 - (quality * 0.3))))),  # Convert quality to ffmpeg scale
            '-y',
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        # Check if thumbnail was generated successfully
        if process.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
            
        # If fast seeking failed, try accurate seeking (slower but more reliable)
        logger.info("Fast seeking failed, trying accurate seeking")
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-ss', str(position),  # More accurate when -ss is after -i
            '-vframes', '1',
            '-vf', f'scale={width}{height_param}',
            '-q:v', str(min(31, max(1, int(31 - (quality * 0.3))))),
            '-y',
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return output_path
        
        # Log error if both attempts failed
        logger.warning(f"Failed to extract frame with direct ffmpeg: {stderr.decode()}")
        return None
        
    except Exception as e:
        logger.error(f"Error in extract_frame_with_ffmpeg: {e}")
        return None

async def extract_frame_with_scene_detection(video_path, output_path, width, quality):
    """Extract a frame using scene detection to find a meaningful frame"""
    try:
        # Create a temporary file for the scene detection output
        temp_dir = tempfile.mkdtemp()
        try:
            # Use ffmpeg's scene detection filter
            height_param = ""  # We don't know aspect ratio here, so just use width
            
            # First try with scene detection
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vf', f'select=gt(scene\\,0.3),scale={width}{height_param}',
                '-frames:v', '1',
                '-q:v', str(min(31, max(1, int(31 - (quality * 0.3))))),
                '-y',
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return output_path
                
            # If that failed, try with keyframe selection
            logger.info("Scene detection failed, trying keyframe selection")
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vf', f'select=eq(pict_type\\,I),scale={width}{height_param}',
                '-frames:v', '1',
                '-q:v', str(min(31, max(1, int(31 - (quality * 0.3))))),
                '-y',
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return output_path
                
            logger.warning(f"Failed to extract frame with scene detection: {stderr.decode()}")
            return None
            
        finally:
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        logger.error(f"Error in extract_frame_with_scene_detection: {e}")
        return None

async def extract_multiple_frames_and_select_best(video_path, output_path, metadata, width, quality):
    """Extract multiple frames and select the best one based on image complexity"""
    try:
        temp_dir = tempfile.mkdtemp()
        try:
            duration = metadata.get('duration', 10)
            if duration <= 0:
                duration = 10
                
            # Extract frames from different positions (10%, 25%, 50%, 75% of video)
            positions = [
                max(1, duration * 0.1),
                max(1, duration * 0.25),
                max(1, duration * 0.5),
                max(1, duration * 0.75)
            ]
            
            frame_files = []
            height_param = ""
            if metadata.get('width') and metadata.get('height') and metadata.get('width') > 0:
                height = int(width * metadata.get('height') / metadata.get('width'))
                height_param = f":{height}"
            
            # Extract frames at different positions
            for i, pos in enumerate(positions):
                temp_file = os.path.join(temp_dir, f"frame_{i}.jpg")
                
                cmd = [
                    'ffmpeg',
                    '-ss', str(pos),
                    '-i', video_path,
                    '-vframes', '1',
                    '-vf', f'scale={width}{height_param}',
                    '-q:v', str(min(31, max(1, int(31 - (quality * 0.3))))),
                    '-y',
                    temp_file
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                await process.communicate()
                
                if os.path.exists(temp_file) and os.path.getsize(temp_file) > 1024:
                    frame_files.append((temp_file, os.path.getsize(temp_file)))
            
            if not frame_files:
                logger.warning("No valid frames could be extracted")
                return None
                
            # Select the best frame (for simplicity, use the largest file size as a proxy for complexity)
            # More complex images typically compress less efficiently, resulting in larger file sizes
            best_frame = max(frame_files, key=lambda x: x[1])[0]
            
            # Copy the best frame to the output path
            shutil.copy2(best_frame, output_path)
            
            return output_path if os.path.exists(output_path) else None
            
        finally:
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            
    except Exception as e:
        logger.error(f"Error in extract_multiple_frames_and_select_best: {e}")
        return None

async def get_keyframes_timestamps(video_path):
    """Get timestamps of keyframes in the video"""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'packet=pts_time,flags',
            '-of', 'json',
            video_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"ffprobe error when getting keyframes: {stderr.decode()}")
            return []
        
        data = json.loads(stdout.decode())
        keyframes = []
        
        for packet in data.get('packets', []):
            # Check if this packet contains a keyframe
            if 'K' in packet.get('flags', ''):
                if 'pts_time' in packet and packet['pts_time'] != 'N/A':
                    keyframes.append(float(packet['pts_time']))
        
        return keyframes
    except Exception as e:
        logger.error(f"Error getting keyframes: {e}")
        return []

async def generate_thumbnail(video_path):
    """Generate thumbnail from video"""
    try:
        # Check if video_path is None or doesn't exist
        if video_path is None or not os.path.exists(video_path):
            logger.error(f"Video file does not exist: {video_path}")
            return None
            
        thumb_path = f"{os.path.splitext(video_path)[0]}_thumb.jpg"
        
        try:
            # Run ffprobe in executor
            probe = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ffmpeg.probe(video_path)
            )
            
            duration = float(probe['format']['duration'])
            time = duration * 0.6
            
            # Run ffmpeg in executor
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: (
                    ffmpeg
                    .input(video_path, ss=time)
                    .output(thumb_path, vframes=1)
                    .overwrite_output()
                    .run(quiet=True)
                )
            )
        except Exception as e:
            logger.error(f"Error generating thumbnail with ffmpeg: {e}")
            return None
        
        return thumb_path if os.path.exists(thumb_path) else None
    except Exception as e:
        logger.error(f"Error generating thumbnail: {e}")
        return None

async def generate_screenshots(video_path, count=10):
    """Generate multiple screenshots from video"""
    try:
        # Check if video_path is None or doesn't exist
        if video_path is None or not os.path.exists(video_path):
            logger.error(f"Video file does not exist: {video_path}")
            return []
            
        try:
            # Run ffprobe in executor
            probe = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ffmpeg.probe(video_path)
            )
            
            duration = float(probe['format']['duration'])
        except Exception as e:
            logger.error(f"Error probing file with ffmpeg: {e}")
            return []
            
        screenshots = []
        base_name = os.path.splitext(video_path)[0]
        
        for i in range(count):
            time = duration * (i + 1) / (count + 1)
            screenshot_path = f"{base_name}_screenshot_{i+1}.jpg"
            
            try:
                # Run ffmpeg in executor
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: (
                        ffmpeg
                        .input(video_path, ss=time)
                        .output(screenshot_path, vframes=1)
                        .overwrite_output()
                        .run(quiet=True)
                    )
                )
                
                if os.path.exists(screenshot_path):
                    screenshots.append(screenshot_path)
            except Exception as e:
                logger.error(f"Error generating screenshot {i+1}: {e}")
        
        return screenshots
    except Exception as e:
        logger.error(f"Error generating screenshots: {e}")
        return []

async def generate_sample_video(video_path, duration=20):
    """Generate a sample video of specified duration"""
    try:
        # Check if video_path is None or doesn't exist
        if video_path is None or not os.path.exists(video_path):
            logger.error(f"Video file does not exist: {video_path}")
            return None
            
        try:
            # Run ffprobe in executor
            probe = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ffmpeg.probe(video_path)
            )
            
            video_duration = float(probe['format']['duration'])
        except Exception as e:
            logger.error(f"Error probing file with ffmpeg: {e}")
            return None
            
        start_time = video_duration * 0.3
        
        if start_time + duration > video_duration:
            start_time = max(0, video_duration - duration)
        
        sample_path = f"{os.path.splitext(video_path)[0]}_sample.mp4"
        
        try:
            # Run ffmpeg in executor
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: (
                    ffmpeg
                    .input(video_path, ss=start_time, t=duration)
                    .output(sample_path, c='copy')
                    .overwrite_output()
                    .run(quiet=True)
                )
            )
        except Exception as e:
            logger.error(f"Error generating sample video with ffmpeg: {e}")
            return None
        
        return sample_path if os.path.exists(sample_path) else None
    except Exception as e:
        logger.error(f"Error generating sample video: {e}")
        return None

def cleanup_files(file_paths):
    """Clean up temporary files"""
    if file_paths is None:
        return
        
    for file_path in file_paths if isinstance(file_paths, list) else [file_paths]:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Removed file: {file_path}")
        except Exception as e:
            logger.error(f"Error removing file {file_path}: {e}")

def format_size(size):
    """Format size in bytes to human readable format"""
    if size is None:
        return "0 B"
        
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "0 B"
        
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
