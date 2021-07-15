import os
import sys
import numpy as np
import pandas as pd
import csv
import time
from collections import deque


def ImportCam(cam_params):
    if cam_params["cameraMake"] == "basler":
        from campy.cameras.basler import cam
    elif cam_params["cameraMake"] == "flir":
        from campy.cameras.flir import cam
    elif cam_params["cameraMake"] == "emu":
        from campy.cameras.emu import cam
    return cam


def LoadSystems(params):
    systems = {}
    cam_params = {}
    makes = GetMakeList(params)
    for m in range(len(makes)):
        cam_params["cameraMake"] = makes[m]
        cam = ImportCam(cam_params)
        systems[makes[m]] = {}
        systems[makes[m]]["system"] = cam.LoadSystem(params)

    return systems


def GetDeviceList(params, systems):
    serials = []
    makes = GetMakeList(params)
    cam_params = {}
    for m in range(len(makes)):
        cam_params["cameraMake"] = makes[m]
        cam = ImportCam(cam_params)
        system = systems[makes[m]]["system"]
        deviceList = cam.GetDeviceList(system)
        serials = []
        for i in range(len(deviceList)):
            serials.append(cam.GetSerialNumber(deviceList[i]))
        systems[makes[m]]["serials"] = serials
        systems[makes[m]]["deviceList"] = deviceList
    return systems


def LoadDevice(cam_params, systems):
    device_list = systems[cam_params["cameraMake"]]["deviceList"]
    cam = ImportCam(cam_params)
    device = cam.LoadDevice(cam_params, device_list)
    return device


def GetMakeList(params):
    cameraMakes = []
    if type(params["cameraMake"]) is list:
        for m in range(len(params["cameraMake"])):
            cameraMakes.append(params["cameraMake"][m])
    elif type(params["cameraMake"]) is str:
        cameraMakes.append(params["cameraMake"])
    makes = list(set(cameraMakes))
    return makes


def GrabData(cam_params):
    grabdata = {"timeStamp": [], "frameNumber": []}

    # Calculate display rate
    if cam_params["displayFrameRate"] <= 0:
        grabdata["frameRatio"] = float('inf')
    elif 0 < cam_params["displayFrameRate"] <= cam_params['frameRate']:
        grabdata["frameRatio"] = int(round(cam_params["frameRate"] / cam_params["displayFrameRate"]))
    else:
        grabdata["frameRatio"] = cam_params["frameRate"]

    # Calculate number of images and chunk length
    grabdata["numImagesToGrab"] = int(round(cam_params["recTimeInSec"] * cam_params["frameRate"]))
    grabdata["chunkLengthInFrames"] = int(round(cam_params["chunkLengthInSec"] * cam_params["frameRate"]))

    return grabdata


def GrabFrames(cam_params, device, writeQueue, dispQueue, stopQueue):
    # Import the cam module
    cam = ImportCam(cam_params)

    # Open the camera object
    camera, cam_params = cam.OpenCamera(cam_params, device)

    # Create dictionary for appending frame number and timestamp information
    grabdata = GrabData(cam_params)

    # Use Basler's default display window on Windows. Not supported on Linux
    if sys.platform == 'win32' and cam_params['cameraMake'] == 'basler':
        dispQueue = cam.OpenImageWindow(cam_params)

    cam_name = cam_params["cameraName"]

    # Start grabbing frames from the camera
    grabbing = cam.StartGrabbing(camera)
    time.sleep(1)
    print(f"{cam_name} ready to trigger.")
    if cam_params["cameraMake"] == "flir":
        grabTimeOutInMilliseconds = cam_params["grabTimeOutInMilliseconds"]
        print(f"You have {grabTimeOutInMilliseconds / 1000} seconds to start the recording for {cam_name}!")

    frameNumber = 0
    frameCount = 0
    while grabbing:
        if stopQueue:
            writeQueue.append('STOP')
            grabbing = False
            cam.CloseCamera(camera, cam_params['cameraName'])
            SaveMetadata(cam_params, grabdata)
            break
        try:
            # Grab image from camera buffer if available
            grabResult = cam.GrabFrame(camera, frameNumber, grabTimeOutInMilliseconds)
        except Exception as err:
            print(f'No frames received from {cam_name} for {grabTimeOutInMilliseconds / 1000} seconds!', err)
            writeQueue.append('STOP')
            grabbing = False
            cam.CloseCamera(camera, cam_params['cameraName'])
            SaveMetadata(cam_params, grabdata)
            break

        try:
            # Append numpy array to writeQueue for writer to append to file
            img = cam.GetImageArray(grabResult, cam_params)
            writeQueue.append(img)
            # Get ImageChunkData and extract TimeStamp and FrameID
            chunkData = cam.GetChunkData(grabResult)
            timeStamp = cam.GetTimeStamp(chunkData)
            frameNumber = cam.GetFrameID(chunkData)
            # Append timeStamp and frameNumber to grabdata
            grabdata['frameNumber'].append(frameNumber)
            grabdata['timeStamp'].append(timeStamp)
            frameCount += 1
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f'Exception in unicam.py GrabFrames for camera {cam_name}', e)
            time.sleep(0.001)

        try:
            if cam_params['displayVideos']:
                # Display converted, downsampled image in the Window
                if frameNumber % grabdata["frameRatio"] == 0:
                    cam.DisplayImage(cam_params, dispQueue, grabResult)

        except KeyboardInterrupt:
            pass
        except Exception as e:
            print('Exception in unicam.py GrabFrames', e)
            time.sleep(0.001)


        if frameCount % grabdata["chunkLengthInFrames"] == 0:
            timeElapsed = timeStamp - grabdata["timeStamp"][0]
            fps_count = int(round(frameCount / timeElapsed))
            print(f'{cam_name} collected {frameCount} frames at {fps_count} fps for {int(round(timeElapsed))} sec.')


        cam.ReleaseFrame(grabResult)


def SaveRecordingMetadata(cam_params, grabdata, base_file_name, cam_name):
    """Save recording metadata to a csv"""
    # Get the frame and time counts to save into metadata
    frame_count = len(grabdata['frameNumber'])
    time_count = grabdata['timeStamp'][-1]
    fps_count = frame_count / time_count

    print(f'{cam_name} saved {frame_count} frames at {fps_count} fps.')

    cam_params['totalFrames'] = frame_count
    cam_params['totalTime'] = time_count
    cam_params['actualFps'] = fps_count

    metadata_filename = os.path.join(folder_name,
                                     base_file_name + '_metadata.csv')
    with open(metadata_filename, 'w', newline='') as f:
        w = csv.writer(f, delimiter=',', quoting=csv.QUOTE_ALL)
        for row in cam_params.items():
            w.writerow(row)

    print(f'Saved metadata.csv for {cam_name}')


def SaveFrameTimestamps(grabdata, base_file_name, cam_name):
    """Save frame timestamps to a csv"""
    x = np.array([grabdata['frameNumber'], grabdata["cameraTime"],
                  grabdata['timeStamp']])
    frametimes_filename = os.path.join(folder_name,
                                       base_file_name + '_frametimes.csv')
    df = pd.DataFrame(data=x.T, columns=['frameNumber', 'cameraTime',
                                         'timeStamp'])
    df = df.convert_dtypes({'frameNumber': 'int'})
    df.to_csv(frametimes_filename)
    print(f'Saved framtimes.csv for {cam_name}')
    return


def SaveMetadata(cam_params, grabdata):
    """save recording metadata and save frame timestamps to CSV files.

    # TODO let user choose which metadata to collect"""
    cam_name = cam_params["cameraName"]

    folder_name = cam_params["videoFolder"]
    if not os.path.isdir(folder_name):
        os.makedirs(folder_name)
        print(f'Made directory {folder_name}.')

    base_file_name = '_'.join((cam_params['cameraName'],
	                           cam_params['record_timestamp']))

    if not grabdata["timeStamp"]:
        print(f'No timestamps found for {cam_name}. No metadata will be saved')
        return

    # Zero timeStamps
    timeFirstGrab = grabdata["timeStamp"][0]
    grabdata["cameraTime"] = grabdata["timeStamp"].copy()
    grabdata["timeStamp"] = [i - timeFirstGrab
                             for i in grabdata["timeStamp"].copy()]

    SaveRecordingMetadata(cam_params, grabdata, base_file_name, cam_name)
    SaveFrameTimestamps(grabdata, base_file_name, cam_name)


def CloseSystems(params, systems):
    makes = GetMakeList(params)
    cam_params = {}
    for m in range(len(makes)):
        cam_params["cameraMake"] = makes[m]
        system = systems[makes[m]]["system"]
        device_list = systems[makes[m]]["deviceList"]
        cam_name = params['cameraNames'][m]
        cam = ImportCam(cam_params)
        try:
            cam.CloseSystem(system, device_list, cam_name)
        except PySpin.SpinnakerException as ex:
            print(f'SpinnakerException at unicam.py CloseSystems for camera {cam_name}: {ex}')
        except Exception as err:
            print(f'Exception at unicam.py CloseSystems for camera {cam_name}: {err}')
