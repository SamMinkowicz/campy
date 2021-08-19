"""
"""
from imageio_ffmpeg import write_frames
import os
import time
import logging
import sys


def ConfigureCPUCompresssion(cam_params):
    """Configure use of CPU to compress the incoming stream"""
    pix_fmt_out = cam_params["pixelFormatOutput"]

    if pix_fmt_out == 'rgb0':
        pix_fmt_out = 'yuv420p'

    if cam_params["codec"] == 'h264':
        codec = 'libx264'
    elif cam_params["codec"] == 'h265':
        codec = 'libx265'

    gpu_params = ['-r:v', str(cam_params["frameRate"]),
                  '-preset', 'fast',
                  '-tune', 'fastdecode',
                  '-crf', cam_params["quality"],
                  '-bufsize', '20M',
                  '-maxrate', '10M',
                  '-bf:v', '4',
                  '-vsync', '0', ]

    return pix_fmt_out, codec, gpu_params


def ConfigureGPUCompresssion(cam_params):
    """Configure use of GPU to compress the incoming stream"""
    pix_fmt_out = cam_params["pixelFormatOutput"]

    if cam_params["gpuMake"] == 'nvidia':
        if cam_params["codec"] == 'h264':
            codec = 'h264_nvenc'
        elif cam_params["codec"] == 'h265':
            codec = 'hevc_nvenc'
        gpu_params = ['-r:v', str(cam_params["frameRate"]),  # important to play nice with vsync '0'
                      '-preset', 'fast',  # set to 'fast', 'llhp', or 'llhq' for h264 or hevc
                      '-qp', cam_params["quality"],
                      '-bf:v', '0',
                      '-vsync', '0',
                                '-2pass', '0',
                                '-gpu', str(cam_params["gpuID"]), ]
    elif cam_params["gpuMake"] == 'amd':
        if pix_fmt_out == 'rgb0':
            pix_fmt_out = 'yuv420p'
        if cam_params["codec"] == 'h264':
            codec = 'h264_amf'
        elif cam_params["codec"] == 'h265':
            codec = 'hevc_amf'
        gpu_params = ['-r:v', str(cam_params["frameRate"]),
                      '-usage', 'lowlatency',
                                '-rc', 'cqp',  # constant quantization parameter
                                '-qp_i', cam_params["quality"],
                                '-qp_p', cam_params["quality"],
                                '-qp_b', cam_params["quality"],
                                '-bf:v', '0',
                                '-hwaccel', 'auto',
                                '-hwaccel_device', str(cam_params["gpuID"]), ]
    elif cam_params["gpuMake"] == 'intel':
        if pix_fmt_out == 'rgb0':
            pix_fmt_out = 'nv12'
        if cam_params["codec"] == 'h264':
            codec = 'h264_qsv'
        elif cam_params["codec"] == 'h265':
            codec = 'hevc_qsv'
        gpu_params = ['-r:v', str(cam_params["frameRate"]),
                      '-bf:v', '0', ]

    return pix_fmt_out, codec, gpu_params


def CreateVideoFolder(video_folder):
    if not os.path.isdir(video_folder):
        os.makedirs(video_folder)
        print(f'Made directory {video_folder}.')

    return video_folder


def BuildFileName(cam_params, splittingVideos=False, video_number=0):
    file_name = '_'.join((cam_params['cameraName'],
                          cam_params['record_timestamp']))

    if splittingVideos:
        file_name = '_'.join((file_name, str(video_number)))

    return '_'.join((file_name, cam_params['videoFilename']))


def GetWriterParams(cam_params):
    # Load defaults
    pix_fmt_out = cam_params["pixelFormatOutput"]
    codec = cam_params["codec"]
    gpu_params = []

    # CPU compression
    if cam_params["gpuID"] == -1:
        print(f'Using CPU to compress the stream.')
        pix_fmt_out, codec, gpu_params = ConfigureCPUCompresssion(cam_params)

    # GPU compression
    else:
        print(f'Using GPU {cam_params["gpuID"]} to compress the stream.')
        pix_fmt_out, codec, gpu_params = ConfigureGPUCompresssion(cam_params)

    return pix_fmt_out, codec, gpu_params


def OpenWriter(cam_params, full_file_name, pix_fmt_out, codec, gpu_params):
    """Initialize writer object (imageio-ffmpeg)"""
    while(True):
        try:
            try:
                writer = write_frames(
                    full_file_name,
                    size=(cam_params["frameWidth"],
                          cam_params["frameHeight"]),  # size [W,H]
                    fps=cam_params["frameRate"],
                    quality=None,
                    codec=codec,
                    # 'bayer_bggr8', 'gray', 'rgb24', 'bgr0', 'yuv420p'
                    pix_fmt_in=cam_params["pixelFormatInput"],
                    pix_fmt_out=pix_fmt_out,
                    bitrate=None,
                    # 'warning', 'quiet', 'info'
                    ffmpeg_log_level=cam_params["ffmpegLogLevel"],
                    input_params=['-an'],  # '-an' no audio
                    output_params=gpu_params,
                )
                writer.send(None)  # Initialize the generator
                break
            except Exception as e:
                logging.error(f'Caught exception in campipe.py: {e}')
                time.sleep(0.1)

        except KeyboardInterrupt:
            break

    return writer


def PrepareNewVideo(cam_params, folder_name, pix_fmt_out,
                    codec, gpu_params, splitting_videos=False, video_number=0):
    file_name = BuildFileName(cam_params,
                              splittingVideos=splitting_videos,
                              video_number=video_number)
    full_file_name = os.path.join(folder_name, file_name)

    # Start ffmpeg video writer
    return OpenWriter(cam_params, full_file_name, pix_fmt_out,
                      codec, gpu_params)


def WriteFrames(cam_params, writeQueue, stopQueue):
    folder_name = CreateVideoFolder(cam_params["videoFolder"])
    pix_fmt_out, codec, gpu_params = GetWriterParams(cam_params)

    video_split_length_sec = cam_params['videoSplitLengthInSec']
    if video_split_length_sec < 0:
        print("videoSplitLengthInSec must be greater than or equal to 0. Writing one video.")
        video_split_length_sec = 0
    # prepare to create a new filename and writer after the specified
    # recording time elapses
    if video_split_length_sec:
        frame_rate = cam_params['frameRate']
        video_split_length_frames = int(frame_rate * video_split_length_sec)
        frame_count = 0

    writer = PrepareNewVideo(cam_params, folder_name, pix_fmt_out,
                             codec, gpu_params, bool(video_split_length_sec),
                             0)
    message = ''


    # Write until interrupted or stop message received
    while(True):
        try:
            if writeQueue:
                if video_split_length_sec and (
                        frame_count % video_split_length_frames == 0):
                    writer.close()
                    writer = PrepareNewVideo(cam_params, folder_name,
                                             pix_fmt_out, codec, gpu_params,
                                             True, frame_count // video_split_length_frames)
                message = writeQueue.popleft()
                if not isinstance(message, str):
                    writer.send(message)
                    frame_count += 1
                elif message == 'STOP':
                    break
            else:
                time.sleep(0.001)
        except KeyboardInterrupt:
            stopQueue.append('STOP')

    # Closing up...
    print(
        f'Closing video writer for {cam_params["cameraName"]}. Please wait...')
    time.sleep(1)
    writer.close()
