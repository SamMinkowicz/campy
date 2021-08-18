"""
CamPy: Python-based multi-camera recording software.
Integrates machine vision camera APIs with ffmpeg real-time compression.
Outputs one MP4 video file for each camera and metadata files

'campy' is the main console.
User inputs are loaded from config yaml file using a command line interface (CLI) into the 'params' dictionary.
Params are assigned to each camera stream in the 'cam_params' dictionary.
	* Camera index is set by 'cameraSelection'.
	* If param is string, it is applied to all cameras.
	* If param is list of strings, it is assigned to each camera, ordered by camera index.
Camera streams are acquired and encoded in parallel using multiprocessing.

Usage:
campy-acquire ./configs/config.yaml
"""
import numpy as np
import os
import time
import datetime
import sys
import threading, queue
from collections import deque
import multiprocessing as mp
from campy import CampyParams
from campy.writer import campipe
from campy.display import display
from campy.cameras import unicam
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
import ast
import yaml
import logging
from shutil import move
import serial


def CombineConfigAndClargs(clargs):
    params = LoadConfig(clargs.config)
    CheckConfig(params, clargs)
    for key, value in clargs.__dict__.items():
        if value is not None:
            params[key] = value
    return params


def CheckConfig(params, clargs):
    invalid_keys = []
    for key in params.keys():
        if key not in clargs.__dict__.keys():
            invalid_keys.append(key)

    if len(invalid_keys) > 0:
        invalid_key_msg = [" %s," % key for key in invalid_keys]
        msg = "Unrecognized keys in the configs: %s" % "".join(invalid_key_msg)
        raise ValueError(msg)


def LoadConfig(config_path):
    try:
        with open(config_path, 'rb') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logging.error(f'Caught exception: {e}')
    return config


def LoadSystemsAndDevices(params):
    systems = unicam.LoadSystems(params)
    systems = unicam.GetDeviceList(params, systems)
    return params, systems


def UnpackParamLists(cam_params, n_cam):
    """If a list is passed for a given parameter, assign the ith element to
    the ith camera"""
    for key in cam_params.keys():
        if isinstance(cam_params[key], list):
            if key == 'ffmpegPath':
                continue

            if len(params[key]) == params["numCams"]:
                cam_params[key] = cam_params[key][n_cam]
            else:
                print(f'{key} list is not the same size as numCams.')
    return cam_params


def UnpackCameraSpecificParams(cam_params):
    """Get parameters that are specific to the given camera.
       These are specified by the camera's serial number"""
    cameraSerialNo = cam_params['cameraSerialNo']
    for key in cam_params.keys():
        if isinstance(cam_params[key], dict):
            if key == 'allCameraSerialNumbers':
                continue

            try:
                cam_params[key] = cam_params[key][int(cameraSerialNo)]
            except KeyError:
                print(f"No {key} found for camera with serial number {cameraSerialNo}")
    return cam_params


def FillWithDefaultParams(cam_params):
    """Assign default parameter if it isn't passed by user"""
    default_params = {"frameRate": 100,
                      "cameraSettings": "./campy/cameras/basler/settings/acA1920-150uc_1152x1024p_100fps_trigger_RGB_p6.pfs",
                      "cameraMake": "flir",
                      "cameraTrigger": 'Line3',
                      "pixelFormatInput": "bayer_rggb8",
                      "pixelFormatOutput": "rgb0",
                      "frameWidth": 1152,
                      "frameHeight": 1024,
                      "ffmpegLogLevel": "quiet",
                      "gpuID": -1,
                      "gpuMake": "nvidia",
                      "codec": "h264",
                      "quality": "21",
                      "chunkLengthInSec": 60,
                      "displayFrameRate": 10,
                      "displayDownsample": 2}

    for key in default_params.keys():
        if key not in cam_params.keys():
            cam_params[key] = default_params[key]
    return cam_params


def CreateCamParams(params, systems, n_cam):
    """Insert camera-specific metadata from parameters into cam_params dictionary"""
    cam_params = params
    cam_params["n_cam"] = n_cam
    cam_params["baseFolder"] = os.getcwd()

    # unpack parameter lists
    cam_params = UnpackParamLists(cam_params, n_cam)

    # Use default params if not present in config or not overwritten by cameraSettings
    cam_params = FillWithDefaultParams(cam_params)

    # Add info about found cameras
    cam_make = cam_params['cameraMake']
    cam_selection = cam_params['cameraSelection']
    try:
        cam_params["device"] = systems[cam_make]["deviceList"][cam_selection]
        cam_params["cameraSerialNo"] = systems[cam_make]["serials"][cam_selection]
    except IndexError:
        print(f'User wants to record from {cam_params["numCams"]} cameras but only found {len(systems[cam_make]["serials"])} cameras. Exiting...')
        return

    # get camera specific parameters
    cam_params = UnpackCameraSpecificParams(cam_params)

    return cam_params


def ParseClargs(parser):
    parser.add_argument(
        "config", metavar="config", help="Campy configuration .yaml file.",
    )
    parser.add_argument(
        "--videoFolder",
        dest="videoFolder",
        help="Folder in which to save videos.",
    )
    parser.add_argument(
        "--videoFilename",
        dest="videoFilename",
        help="Name for video output file.",
    )
    parser.add_argument(
        "--frameRate",
        dest="frameRate",
        type=int,
        help="Frame rate equal to trigger frequency.",
    )
    parser.add_argument(
        "--recTimeInSec",
        dest="recTimeInSec",
        type=int,
        help="Recording time in seconds.",
    )
    parser.add_argument(
        "--numCams",
        dest="numCams",
        type=int,
        help="Number of cameras.",
    )
    parser.add_argument(
        "--cameraName",
        dest="cameraName",
        type=ast.literal_eval,
        help="Names assigned to the cameras in the order of cameraSelection.",
    )
    parser.add_argument(
        "--cameraSelection",
        dest="cameraSelection",
        type=int,
        help="Selects and orders camera indices to include in the recording. List length must be equal to numCams",
    )
    parser.add_argument(
        "--cameraSettings",
        dest="cameraSettings",
        type=ast.literal_eval,
        help="Path to camera settings file.",
    )
    parser.add_argument(
        "--cameraTrigger",
        dest="cameraTrigger",
        type=ast.literal_eval,
        help="String indicating trigger input to camera (e.g. 'Line3').",
    )
    parser.add_argument(
        "--frameHeight",
        dest="frameHeight",
        type=int,
        help="Frame height in pixels.",
    )
    parser.add_argument(
        "--frameWidth",
        dest="frameWidth",
        type=int,
        help="Frame width in pixels.",
    )
    parser.add_argument(
        "--offsetX",
        dest="offsetX",
        type=int,
        help="Width offset in pixels.",
    )
    parser.add_argument(
        "--offsetY",
        dest="offsetY",
        type=int,
        help="Height offset in pixels.",
    )
    parser.add_argument(
        "--cameraMake",
        dest="cameraMake",
        type=ast.literal_eval,
        help="Company that produced the camera. Currently supported: 'basler'.",
    )
    parser.add_argument(
        "--pixelFormatInput",
        dest="pixelFormatInput",
        type=ast.literal_eval,
        help="Pixel format input. Use 'rgb24' for RGB or 'bayer_bggr8' for 8-bit bayer pattern.",
    )
    parser.add_argument(
        "--pixelFormatOutput",
        dest="pixelFormatOutput",
        type=ast.literal_eval,
        help="Pixel format output. Use 'rgb0' for best results.",
    )
    parser.add_argument(
        "--ffmpegPath",
        dest="ffmpegPath",
        help="Location of ffmpeg binary for imageio.",
    )
    parser.add_argument(
        "--ffmpegLogLevel",
        dest="ffmpegLogLevel",
        type=ast.literal_eval,
        help="Sets verbosity level for ffmpeg logging. ('quiet' (no warnings), 'warning', 'info' (real-time stats)).",
    )
    parser.add_argument(
        "--gpuID",
        dest="gpuID",
        type=int,
        help="List of integers assigning the gpu index to stream each camera. Set to -1 to stream with CPU.",
    )
    parser.add_argument(
        "--gpuMake",
        dest="gpuMake",
        type=ast.literal_eval,
        help="Company that produced the GPU. Currently supported: 'nvidia', 'amd', 'intel' (QuickSync).",
    )
    parser.add_argument(
        "--codec",
        dest="codec",
        type=ast.literal_eval,
        help="Video codec for compression Currently supported: 'h264', 'h265' (hevc).",
    )
    parser.add_argument(
        "--quality",
        dest="quality",
        type=ast.literal_eval,
        help="Compression quality. Lower number is less compression and larger files. '23' is visually lossless.",
    )
    parser.add_argument(
        "--chunkLengthInSec",
        dest="chunkLengthInSec",
        type=int,
        help="Length of video chunks in seconds for reporting recording progress.",
    )
    parser.add_argument(
        "--displayVideos",
        dest="displayVideos",
        type=bool,
        help="Enable video display.",
    )
    parser.add_argument(
        "--displayFrameRate",
        dest="displayFrameRate",
        type=int,
        help="Display frame rate in Hz. Max ~30.",
    )
    parser.add_argument(
        "--displayDownsample",
        dest="displayDownsample",
        type=int,
        help="Downsampling factor for displaying images.",
    )
    parser.add_argument(
        "--exposureTimeInUs",
        dest="exposureTimeInUs",
        type=int,
        help="Exposure time in microseconds (us). Only used for FLIR cameras",
    )
    parser.add_argument(
        "--gain",
        dest="gain",
        type=int,
        help="Gain in dB. Only used for FLIR cameras",
    )
    parser.add_argument(
        "--bufferMode",
        dest="bufferMode",
        type=str,
        help="Buffer handling mode. Only used for FLIR cameras",
    )
    parser.add_argument(
        "--bufferSize",
        dest="bufferSize",
        type=int,
        help="Buffer count size. Only used for FLIR cameras",
    )
    parser.add_argument(
        "--disableGamma",
        dest="disableGamma",
        type=bool,
        help="Gamma correction disabling. Only used for FLIR cameras",
    )
    parser.add_argument(
        "--gamma",
        dest="gamma",
        type=str,
        help="Gamma correction. Only used for FLIR cameras",
    )
    parser.add_argument(
        "--blackLevel",
        dest="blackLevel",
        type=str,
        help=". Only used for FLIR cameras",
    )
    parser.add_argument(
        "--grabTimeOutInMilliseconds",
        dest="grabTimeOutInMilliseconds",
        type=int,
        help="Frame grabbing timeout in milliseconds. Only used for FLIR cameras. If camera doesn't receive frames"
             "for this amount of time, it will stop the recording.",
    )
    parser.add_argument(
        "--triggerType",
        dest="triggerType",
        type=str,
        help="Trigger type: hardware or software. Only used for FLIR cameras",
    )
    parser.add_argument(
        "--throughputLimit",
        dest="throughputLimit",
        type=int,
        help="Maximum bandwidth (bps) of the data coming out of the camera. Only used for FLIR cameras",
    )
    parser.add_argument(
        "--controlRecordingTimeInArduino",
        dest="controlRecordingTimeInArduino",
        type=bool,
        help="Whether to control the recording time in the Arduino",
    )
    parser.add_argument(
        "--arduinoPort",
        dest="arduinoPort",
        type=str,
        help="Arduino's serial port",
    )
    parser.add_argument(
        "--arduinoBaudRate",
        dest="arduinoBaudRate",
        type=int,
        help="Arduino baud rate.",
    )
    parser.add_argument(
        "--allCameraSerialNumbers",
        dest="allCameraSerialNumbers",
        type=dict,
        help="Camera serial numbers",
    )
    clargs = parser.parse_args()
    return clargs


def AcquireOneCamera(n_cam):
    # Initializes metadata dictionary for this camera stream
    # and inserts important configuration details

    # Load camera parameters from config
    cam_params = CreateCamParams(params, systems, n_cam)
    if not cam_params:
        return
    cam_name = cam_params['cameraName']

    timestamp = f"{datetime.datetime.now():%Y-%m-%d-%H-%M}"
    cam_params['record_timestamp'] = timestamp

    # Initialize queues for video writer and stop message
    writeQueue = deque()
    stopQueue = deque([], 1)

    # Start image window display thread
    dispQueue = deque([], 2)
    # if cam_params["cameraMake"] != 'flir':
    threading.Thread(
        target=display.DisplayFrames,
        daemon=True,
        args=(cam_params, dispQueue,),
    ).start()

    # Load camera device
    device = unicam.LoadDevice(cam_params, systems)

    # Start grabbing frames ('producer' thread)
    frame_grab_thread = threading.Thread(
        target=unicam.GrabFrames,
        args=(cam_params, device, writeQueue, dispQueue, stopQueue,),
    )
    frame_grab_thread.start()

    # Start video file writer (main 'consumer' thread)
    campipe.WriteFrames(cam_params, writeQueue, stopQueue)

    frame_grab_thread.join()


def Main():
    # Optionally, user can manually set path to find ffmpeg binary.
    if params["ffmpegPath"]:
        os.environ["IMAGEIO_FFMPEG_EXE"] = params["ffmpegPath"]

    if params['controlRecordingTimeInArduino']:
        print('Arduino will be controlling recording time')
        # send recording length to the arduino
        try:
            arduino = serial.Serial(port=params['arduinoPort'],
                                    baudrate=params['arduinoBaudRate'])
            time.sleep(3)  # wait for the port to be opened
            arduino.write(str(params['recTimeInSec']).encode())
        except Exception as e:
            print(f"Cannot communicate with the Arduino: {e}")
            params['controlRecordingTimeInArduino'] = False

    if sys.platform == "win32":
        pool = mp.Pool(processes=params['numCams'])
        pool.map(AcquireOneCamera, range(0, params['numCams']))
        # Close the systems and devices properly
        unicam.CloseSystems(params, systems)

    elif sys.platform == "linux" or sys.platform == "linux2":
        ctx = mp.get_context("spawn")  # for linux compatibility
        pool = ctx.Pool(processes=params['numCams'])
        p = pool.map_async(AcquireOneCamera, range(0, params['numCams']))
        p.get()

    if params['controlRecordingTimeInArduino']:
        arduino.close()


parser = ArgumentParser(
    description="Campy CLI",
    formatter_class=ArgumentDefaultsHelpFormatter,
)
clargs = ParseClargs(parser)
params = CombineConfigAndClargs(clargs)
params, systems = LoadSystemsAndDevices(params)
