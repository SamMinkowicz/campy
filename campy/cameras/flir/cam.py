"""
"""
import PySpin
from campy.cameras import unicam
import os
import time
import logging
import sys
import numpy as np
import csv
from random import randint

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"


class ImageNotCompleteException(Exception):
    """Exception raised for errors in the input.

    Attributes:
        expression -- input expression in which the error occurred
        message -- explanation of the error
    """

    def __init__(self, expression, message):
        self.expression = expression
        self.message = message


class TriggerType:
    SOFTWARE = 1
    HARDWARE = 2


def ConfigureTrigger(cam_params, camera, cam_name):
    """
    This function configures the camera to use a trigger. First, trigger mode is
    ensured to be off in order to select the trigger source. Trigger mode is
    then enabled, which has the camera capture only a single image upon the
    execution of the chosen trigger.
     :param cam: Camera to configure trigger for.
     :type cam: CameraPtr
     :return: True if successful, False otherwise.
     :rtype: bool
    """

    print(f'*** CONFIGURING TRIGGER for {cam_name}***')
    if cam_params['triggerType'] == 'software':
        CHOSEN_TRIGGER = TriggerType.SOFTWARE
        print('Software trigger chosen...')
    elif cam_params['triggerType'] == 'hardware':
        CHOSEN_TRIGGER = TriggerType.HARDWARE
        print('Hardware trigger chosen...')
    else:
        print('triggerType must be either "software" or "hardware"')
        return False

    try:
        result = True
        # Ensure trigger mode off
        # The trigger must be disabled in order to configure whether the source
        # is software or hardware.
        if camera.TriggerMode.GetAccessMode() != PySpin.RW:
            print('Unable to disable trigger mode (node retrieval). Aborting...')
            return False
        camera.TriggerMode.SetValue(PySpin.TriggerMode_Off)
        print('Trigger mode disabled...')

        # Switch on the TriggerOverlap (important for high frame rates/exposures)
        camera.TriggerOverlap.SetValue(PySpin.TriggerOverlap_ReadOut)

        # Select trigger source
        # The trigger source must be set to hardware or software while trigger
        # mode is off.
        if camera.TriggerSource.GetAccessMode() != PySpin.RW:
            print('Unable to get trigger source (node retrieval). Aborting...')
            return False

        if CHOSEN_TRIGGER == TriggerType.SOFTWARE:
            camera.TriggerSource.SetValue(PySpin.TriggerSource_Software)
        elif CHOSEN_TRIGGER == TriggerType.HARDWARE:
            eval('camera.TriggerSource.SetValue(PySpin.TriggerSource_%s)' % cam_params['cameraTrigger'])

        # Turn trigger mode on
        # Once the appropriate trigger source has been set, turn trigger mode
        # on in order to retrieve images using the trigger.
        camera.TriggerMode.SetValue(PySpin.TriggerMode_On)
        print('Trigger mode turned back on...')

    except PySpin.SpinnakerException as ex:
        print('Error: %s' % ex)
        return False

    return result


def configure_exposure(cam, exposure_time: int, cam_name):
    """
    This function configures a custom exposure time. Automatic exposure is turned off in order to allow for the
    customization, and then the custom setting is applied.
     :param cam: Camera to configure exposure for.
     :type cam: CameraPtr
     :param exposure_time: exposure time in microseconds
     :type exposure_time: int
     :return: True if successful, False otherwise.
     :rtype: bool
    """

    print(f'*** CONFIGURING EXPOSURE for {cam_name} ***')

    try:
        result = True

        # Turn off automatic exposure mode
        #
        # *** NOTES *** Automatic exposure prevents the manual configuration of exposure times and needs to be turned
        # off. Enumerations representing entry nodes have been added to QuickSpin. This allows for the much easier
        # setting of enumeration nodes to new values.
        #
        # The naming convention of QuickSpin enums is the name of the enumeration node followed by an underscore and
        # the symbolic of the entry node. Selecting "Off" on the "ExposureAuto" node is thus named "ExposureAuto_Off".

        if cam.ExposureAuto.GetAccessMode() != PySpin.RW:
            print('Unable to disable automatic exposure. Aborting...')
            return False

        cam.ExposureAuto.SetValue(PySpin.ExposureAuto_Off)
        print('Automatic exposure disabled...')

        # Set exposure time manually; exposure time recorded in microseconds
        #
        # *** NOTES *** Notice that the node is checked for availability and writability prior to the setting of the
        # node. In QuickSpin, availability and writability are ensured by checking the access mode.
        #
        # Further, it is ensured that the desired exposure time does not exceed the maximum. Exposure time is counted
        # in microseconds - this can be found out either by retrieving the unit with the GetUnit() method or by
        # checking SpinView.

        if cam.ExposureTime.GetAccessMode() != PySpin.RW:
            print('Unable to set exposure time. Aborting...')
            return False

        # Ensure desired exposure time does not exceed the maximum
        exposure_time_to_set = exposure_time
        exposure_time_to_set = min(cam.ExposureTime.GetMax(), exposure_time_to_set)
        cam.ExposureTime.SetValue(exposure_time_to_set)
        print(f'Shutter time set to {exposure_time_to_set} us...\n')

    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}')
        result = False

    return result


def configure_gain(cam, gain: float, cam_name):
    """
    This function configures the camera gain.
    :param cam: Camera to acquire images from.
    :type cam: CameraPtr
    :param gain: gain in dB
    :type gain: float
    :return: True if successful, False otherwise.
    :rtype: bool
    """

    print(f'*** CONFIGURING ACQUISITION MODE for {cam_name} ***')
    try:
        result = True

        # Retrieve GenICam nodemap (nodemap)
        nodemap = cam.GetNodeMap()

        # Retrieve node
        node_gainauto_mode = PySpin.CEnumerationPtr(nodemap.GetNode("GainAuto"))
        if not PySpin.IsAvailable(node_gainauto_mode) or not PySpin.IsWritable(node_gainauto_mode):
            print('Unable to configure gain (enum retrieval). Aborting...')
            return False

        # EnumEntry node (always associated with an Enumeration node)
        node_gainauto_mode_off = node_gainauto_mode.GetEntryByName("Off")
        if not PySpin.IsAvailable(node_gainauto_mode_off):
            print('Unable to configure gain (entry retrieval). Aborting...')
            return False

        # Turn off Auto Gain
        node_gainauto_mode.SetIntValue(node_gainauto_mode_off.GetValue())
        print("Auto gain set to 'off'")

        # Retrieve gain node (float)
        node_gain = PySpin.CFloatPtr(nodemap.GetNode("Gain"))
        if not PySpin.IsAvailable(node_gain) or not PySpin.IsWritable(node_gain):
            print('Unable to configure gain (float retrieval). Aborting...')
            return False

        max_gain = cam.Gain.GetMax()

        if gain > cam.Gain.GetMax():
            print(f"Max. gain is {max_gain}dB!")
            gain = max_gain
        elif gain <= 0:
            gain = 0.0

        # Set gain
        node_gain.SetValue(float(gain))
        print(f'Gain set to {gain} dB.\n')

    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}')
        return False

    return result


def disable_gamma(cam, cam_name):
    """This function disables the gamma correction.
     :param cam: Camera to disable gamma correction.
     :type cam: CameraPtr
     """

    print(f'*** DISABLING GAMMA CORRECTION for {cam_name} ***')

    try:
        result = True

        # Retrieve GenICam nodemap (nodemap)
        nodemap = cam.GetNodeMap()

        # Retrieve node (boolean)
        node_gamma_enable_bool = PySpin.CBooleanPtr(nodemap.GetNode("GammaEnable"))

        if not PySpin.IsAvailable(node_gamma_enable_bool) or not PySpin.IsWritable(node_gamma_enable_bool):
            print('Unable to disable gamma (boolean retrieval). Aborting...')
            return False

        # Set value to False (disable gamma correction)
        node_gamma_enable_bool.SetValue(False)
        print('Gamma correction disabled.\n')

    except PySpin.SpinnakerException as ex:
        print('Error: %s' % ex)
        return False

    return result


def configure_buffer(cam, cam_name, bufferMode='OldestFirst', bufferSize=100):
    """configure buffer size and mode. Mode must be: OldestFirst, NewestFirst,
       NewestOnly or OldestFirstOverwrite."""

    print(f'*** CONFIGURING BUFFER for {cam_name} ***')
    result = True
    # Retrieve Stream Parameters device nodemap
    s_node_map = cam.GetTLStreamNodeMap()

    # Retrieve Buffer Handling Mode Information
    handling_mode = PySpin.CEnumerationPtr(s_node_map.GetNode('StreamBufferHandlingMode'))
    if not PySpin.IsAvailable(handling_mode) or not PySpin.IsWritable(handling_mode):
        print('Unable to set Buffer Handling mode (node retrieval). Aborting...\n')
        return False

    handling_mode_entry = PySpin.CEnumEntryPtr(handling_mode.GetCurrentEntry())
    if not PySpin.IsAvailable(handling_mode_entry) or not PySpin.IsReadable(handling_mode_entry):
        print('Unable to set Buffer Handling mode (Entry retrieval). Aborting...\n')
        return False

    # Set stream buffer Count Mode to manual
    stream_buffer_count_mode = PySpin.CEnumerationPtr(s_node_map.GetNode('StreamBufferCountMode'))
    if not PySpin.IsAvailable(stream_buffer_count_mode) or not PySpin.IsWritable(stream_buffer_count_mode):
        print('Unable to set Buffer Count Mode (node retrieval). Aborting...\n')
        return False

    stream_buffer_count_mode_manual = PySpin.CEnumEntryPtr(stream_buffer_count_mode.GetEntryByName('Manual'))
    if not PySpin.IsAvailable(stream_buffer_count_mode_manual) or not PySpin.IsReadable(
            stream_buffer_count_mode_manual):
        print('Unable to set Buffer Count Mode entry (Entry retrieval). Aborting...\n')
        return False

    stream_buffer_count_mode.SetIntValue(stream_buffer_count_mode_manual.GetValue())
    print('Stream Buffer Count Mode set to manual...')

    # Retrieve and modify Stream Buffer Count
    buffer_count = PySpin.CIntegerPtr(s_node_map.GetNode('StreamBufferCountManual'))
    if not PySpin.IsAvailable(buffer_count) or not PySpin.IsWritable(buffer_count):
        print('Unable to set Buffer Count (Integer node retrieval). Aborting...\n')
        return False

    # Display Buffer Info
    print(f'\nDefault Buffer Handling Mode: {handling_mode_entry.GetDisplayName()}')
    print(f'Maximum Buffer Count: {buffer_count.GetMax()}')
    buffer_count.SetValue(bufferSize)
    print(f'Buffer count now set to: {buffer_count.GetValue()}')

    bufferModes = ['OldestFirst', 'NewestFirst', 'NewestOnly',
                   'OldestFirstOverwrite']

    if bufferMode in bufferModes:
        handling_mode_entry = handling_mode.GetEntryByName(bufferMode)
        handling_mode.SetIntValue(handling_mode_entry.GetValue())
        print(f'\nBuffer Handling Mode has been set to {handling_mode_entry.GetDisplayName()}')
    else:
        print("\nbufferMode should be 'OldestFirst', 'NewestFirst', 'NewestOnly' or 'OldestFirstOverwrite'")
        return False

    return result


def enableChunkDataPayloads(cam, chunkDataToRetreive, cam_name):
    """
    This function configures the camera to add chunk data to each image. It does
    this by enabling each type of chunk data before enabling chunk data mode.
    When chunk data is turned on, the data is made available in both the nodemap
    and each image.

    :param nodemap: Transport layer device nodemap.
    :type nodemap: INodeMap
    :return: True if successful, False otherwise
    :rtype: bool
    """
    try:
        result = True
        print(f'\n*** CONFIGURING CHUNK DATA for {cam_name} ***')

        # Activate chunk mode
        #
        # *** NOTES ***
        # Once enabled, chunk data will be available at the end of the payload
        # of every image captured until it is disabled. Chunk data can also be
        # retrieved from the nodemap.

        nodemap = cam.GetNodeMap()
        chunk_mode_active = PySpin.CBooleanPtr(nodemap.GetNode('ChunkModeActive'))

        if PySpin.IsAvailable(chunk_mode_active) and PySpin.IsWritable(chunk_mode_active):
            chunk_mode_active.SetValue(True)

        print('Chunk mode activated...')

        # Enable all types of chunk data
        #
        # *** NOTES ***
        # Enabling chunk data requires working with nodes: "ChunkSelector"
        # is an enumeration selector node and "ChunkEnable" is a boolean. It
        # requires retrieving the selector node (which is of enumeration node
        # type), selecting the entry of the chunk data to be enabled, retrieving
        # the corresponding boolean, and setting it to be true.
        #
        # In this example, all chunk data is enabled, so these steps are
        # performed in a loop. Once this is complete, chunk mode still needs to
        # be activated.
        chunk_selector = PySpin.CEnumerationPtr(nodemap.GetNode('ChunkSelector'))

        if not PySpin.IsAvailable(chunk_selector) or not PySpin.IsReadable(chunk_selector):
            print('Unable to retrieve chunk selector. Aborting...\n')
            return False

        # Retrieve entries
        #
        # *** NOTES ***
        # PySpin handles mass entry retrieval in a different way than the C++
        # API. Instead of taking in a NodeList_t reference, GetEntries() takes
        # no parameters and gives us a list of INodes. Since we want these INodes
        # to be of type CEnumEntryPtr, we can use a list comprehension to
        # transform all of our collected INodes into CEnumEntryPtrs at once.
        entries = [PySpin.CEnumEntryPtr(chunk_selector_entry) for chunk_selector_entry in chunk_selector.GetEntries()]
        print('Enabling entries...')

        # Iterate through our list and select each entry node to enable
        for chunk_selector_entry in entries:
            # Go to next node if problem occurs
            if not PySpin.IsAvailable(chunk_selector_entry) or not PySpin.IsReadable(chunk_selector_entry):
                continue

            chunk_selector.SetIntValue(chunk_selector_entry.GetValue())

            # only enable the chunk data (metadata) of interest
            if chunk_selector_entry.GetSymbolic() not in chunkDataToRetreive:
                continue

            chunk_str = '\t {}:'.format(chunk_selector_entry.GetSymbolic())

            # Retrieve corresponding boolean
            chunk_enable = PySpin.CBooleanPtr(nodemap.GetNode('ChunkEnable'))

            # Enable the boolean, thus enabling the corresponding chunk data
            if not PySpin.IsAvailable(chunk_enable):
                print(f'{chunk_str} not available\n')
                result = False
            elif chunk_enable.GetValue() is True:
                print(f'{chunk_str} enabled')
            elif PySpin.IsWritable(chunk_enable):
                chunk_enable.SetValue(True)
                print(f'{chunk_str} enabled')
            else:
                print(f'{chunk_str} not writable\n')
                result = False

    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}')
        result = False

    return result


def ConfigureCustomImageSettings(cam_params, nodemap, cam_name):
    """
    Configures a number of settings on the camera including offsets  X and Y, width,
    height, and pixel format. These settings must be applied before BeginAcquisition()
    is called; otherwise, they will be read only. Also, it is important to note that
    settings are applied immediately. This means if you plan to reduce the width and
    move the x offset accordingly, you need to apply such changes in the appropriate order.
    :param nodemap: GenICam nodemap.
    :type nodemap: INodeMap
    :return: True if successful, False otherwise.
    :rtype: bool
    """
    print(f'\n*** CONFIGURING CUSTOM IMAGE SETTINGS for {cam_name} ***')
    try:
        result = True

        width_to_set = cam_params["frameWidth"]
        if width_to_set % 16 != 0:
            print(f"width_to_set = {width_to_set} is not divisible by 16, this may create problems with ffmpeg. width_to_set will "
                  "be increased to the nearest value that is divisible by 16")
            while width_to_set % 16 != 0:
                width_to_set += 1
            print(f"width_to_set is set to {width_to_set}")
            cam_params["frameWidth"] = width_to_set
        height_to_set = cam_params["frameHeight"]
        if height_to_set % 16 != 0:
            print(f"height_to_set = {height_to_set} is not divisible by 16, this may create problems with ffmpeg. height_to_set will "
                  "be increased to the nearest value that is divisible by 16")
            while height_to_set % 16 != 0:
                height_to_set += 1
            print(f"height_to_set is set to {height_to_set}")
            cam_params["frameHeight"] = height_to_set

        # ToDo: Reset the ROI back to default

        # Set maximum width
        #
        # *** NOTES ***
        # Other nodes, such as those corresponding to image width and height,
        # might have an increment other than 1. In these cases, it can be
        # important to check that the desired value is a multiple of the
        # increment. However, as these values are being set to the maximum,
        # there is no reason to check against the increment.
        node_width = PySpin.CIntegerPtr(nodemap.GetNode('Width'))
        max_w = node_width.GetMax()
        if PySpin.IsAvailable(node_width) and PySpin.IsWritable(node_width):
            # width_to_set = node_width.GetMax()
            width_to_set = cam_params["frameWidth"]
            node_width.SetValue(width_to_set)
            print(f'Width set to {node_width.GetValue()}...')
            offset_x = cam_params['offsetX']
            if offset_x % 4 != 0:
                print(f"offset_x = {offset_x} is not divisible by 4, this may create problems with the camera. offset_x will be "
                      "increased to the nearest value that is divisible by 4")
                while offset_x % 4 != 0:
                    offset_x += 1
                print(f"offset_x is set to {offset_x}")
                cam_params["offset_x"] = offset_x
            node_offset_x = PySpin.CIntegerPtr(nodemap.GetNode('OffsetX'))
            if PySpin.IsAvailable(node_offset_x) and PySpin.IsWritable(node_offset_x):
                node_offset_x.SetValue(offset_x)
            else:
                print('OffsetX cannot be set!')
        else:
            print('Width not available...')

        # Set maximum height
        # *** NOTES ***
        # A maximum is retrieved with the method GetMax(). A node's minimum and
        # maximum should always be a multiple of its increment.
        node_height = PySpin.CIntegerPtr(nodemap.GetNode('Height'))
        max_h = node_height.GetMax()
        if PySpin.IsAvailable(node_height) and PySpin.IsWritable(node_height):
            # height_to_set = node_height.GetMax()
            height_to_set = cam_params["frameHeight"]
            node_height.SetValue(height_to_set)
            print(f'Height set to {node_height.GetValue()}...')
            offset_y = cam_params['offsetY']
            if offset_y % 4 != 0:
                print(f"offset_y = {offset_y} is not divisible by 4, this may create problems with the camera. offset_y will be "
                      "increased to the nearest value that is divisible by 4")
                while offset_y % 4 != 0:
                    offset_y += 1
                print(f"offset_y is set to {offset_y}\n")
                cam_params["offset_y"] = offset_y
            node_offset_y = PySpin.CIntegerPtr(nodemap.GetNode('OffsetY'))
            if PySpin.IsAvailable(node_offset_y) and PySpin.IsWritable(node_offset_y):
                node_offset_y.SetValue(offset_y)
            else:
                print('OffsetY cannot be set!\n')
        else:
            print('Height not available...\n')

    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}\n')
        return False

    return result, width_to_set, height_to_set


def ConfigureAcquisitionMode(camera, cam_name):
    """Set acquisition mode to continuous"""

    print(f'\n*** CONFIGURING ACQUISITION MODE for {cam_name} ***')

    try:
        result = True

        node_acquisition_mode = PySpin.CEnumerationPtr(
            camera.GetNodeMap().GetNode('AcquisitionMode'))
        if not PySpin.IsAvailable(node_acquisition_mode) or not PySpin.IsWritable(node_acquisition_mode):
            print(f'Unable to set acquisition mode to continuous (node retrieval; camera {i}). Aborting... \n')
            return False
        node_acquisition_mode_continuous = node_acquisition_mode.GetEntryByName('Continuous')
        if not PySpin.IsAvailable(node_acquisition_mode_continuous) or not PySpin.IsReadable(node_acquisition_mode_continuous):
            print('Unable to set acquisition mode to continuous (entry \'continuous\' retrieval %d). \
            Aborting... \n')
            return False
        acquisition_mode_continuous = node_acquisition_mode_continuous.GetValue()
        node_acquisition_mode.SetIntValue(acquisition_mode_continuous)
        print('Acquisition mode set to continuous\n')

    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}')
        return False

    return result


def SetThroughputLimit(camera, cam_name):
    try:
        node_throughput_limit = PySpin.CIntegerPtr(
            camera.GetNodeMap().GetNode('DeviceLinkThroughputLimit'))
        if PySpin.IsAvailable(node_throughput_limit) and PySpin.IsWritable(node_throughput_limit):
            # throughput_limit_to_set = cam_params["ThroughputLimit"]
            # throughput_limit_to_set = 380000000
            throughput_limit_to_set = 380000000
            node_throughput_limit.SetValue(throughput_limit_to_set)
            print(f'\nThroughput limit for {cam_name} set to {node_throughput_limit.GetValue()}...')
            return True
        else:
            print('Throughput limit not available...\n')
            return False

    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}\n')


def SetFrameRate(camera, cam_name, frame_rate_to_set):
    # the frame rate on the camera needs to be >= to the hardware triggered
    # frame rate
    frame_rate_to_set = 1.1*frame_rate_to_set

    try:
        node_enable_frame_rate = PySpin.CBooleanPtr(
            camera.GetNodeMap().GetNode('AcquisitionFrameRateEnable'))
        if PySpin.IsAvailable(node_enable_frame_rate) and PySpin.IsWritable(node_enable_frame_rate):
            node_enable_frame_rate.SetValue(True)
        else:
            print(f'Cannot set frame rate limit for {cam_name}...\n')

        node_frame_rate = PySpin.CFloatPtr(
            camera.GetNodeMap().GetNode('AcquisitionFrameRate'))
        if PySpin.IsAvailable(node_enable_frame_rate) and PySpin.IsWritable(node_enable_frame_rate):
            node_frame_rate.SetValue(frame_rate_to_set)
            print(f'\n{cam_name} set to acquire frames up to {node_frame_rate.GetValue()} fps...')
        else:
            print(f'Cannot set frame rate limit for {cam_name}...\n')

    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}\n')


def PrintDeviceInfo(nodemap, cam_num):
    """
    This function prints the device information of the camera from the transport
    layer; please see NodeMapInfo example for more in-depth comments on printing
    device information from the nodemap.
    :param nodemap: Transport layer device nodemap.
    :param cam_num: Camera number.
    :type nodemap: INodeMap
    :type cam_num: int
    :returns: True if successful, False otherwise.
    :rtype: bool
    """

    print(f'Printing device information for camera {cam_num}...')
    try:
        result = True
        node_device_information = PySpin.CCategoryPtr(nodemap.GetNode('DeviceInformation'))
        if PySpin.IsAvailable(node_device_information) and PySpin.IsReadable(node_device_information):
            features = node_device_information.GetFeatures()
            for feature in features:
                node_feature = PySpin.CValuePtr(feature)
                try:
                    print(f'{node_feature.GetName()}: {node_feature.ToString()}' if PySpin.IsReadable(node_feature) else 'Node not readable')
                except:
                    pass
        else:
            print('Device control information not available.')
        print()
        return result
    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}')
        return False


def LoadSystem(params):
    return PySpin.System.GetInstance()


def GetDeviceList(system):
    return system.GetCameras()


def LoadDevice(cam_params, device_list):
    return device_list.GetByIndex(cam_params["cameraSelection"])


def GetSerialNumber(device):
    node_device_serial_number = PySpin.CStringPtr(device.GetTLDeviceNodeMap().GetNode('DeviceSerialNumber'))
    if PySpin.IsAvailable(node_device_serial_number) and PySpin.IsReadable(node_device_serial_number):
        device_serial_number = node_device_serial_number.GetValue()
    else:
        device_serial_number = []
    return device_serial_number


def OpenCamera(cam_params, camera):
    # Retrieve TL device nodemap
    nodemap_tldevice = camera.GetTLDeviceNodeMap()
    # Print device information
    PrintDeviceInfo(nodemap_tldevice, cam_params["cameraSelection"])

    # Initialize camera object
    camera.Init()

    # Load camera settings
    cam_params = LoadSettings(cam_params, camera)

    print(f"Opened {cam_params['cameraName']}, serial#: {cam_params['cameraSerialNo']}")
    return camera, cam_params


def LoadSettings(cam_params, camera):
    cam_name = cam_params['cameraName']

    # set bandwidth of transport from camera
    SetThroughputLimit(camera, cam_name)

    # set acquisition mode to continuous
    acquisitionConfig = ConfigureAcquisitionMode(camera, cam_name=cam_name)
    cam_params["acquisitionConfig"] = acquisitionConfig

    SetFrameRate(camera, cam_name, cam_params['frameRate'])

    # Configure trigger
    trigConfig = ConfigureTrigger(cam_params, camera, cam_name=cam_name)
    cam_params["trigConfig"] = trigConfig

    # Configure custom image settings
    settingsConfig, frameWidth, frameHeight = ConfigureCustomImageSettings(cam_params, camera.GetNodeMap(), cam_name=cam_name)
    cam_params["settingsConfig"] = settingsConfig
    cam_params["frameWidth"] = frameWidth
    cam_params["frameHeight"] = frameHeight

    # Configure exposure, gain, gamma, buffer and chunk data mode for metadata (eg. timestamp and frame no information)
    if configure_exposure(
        cam=camera, exposure_time=cam_params["exposureTimeInUs"],
        cam_name=cam_name):
        if configure_gain(cam=camera, gain=cam_params["gain"],
                          cam_name=cam_name):
            if configure_buffer(cam=camera, cam_name=cam_name,
                                bufferMode=cam_params["bufferMode"],
                                bufferSize=cam_params["bufferSize"]):
                print('Exposure, gain and buffer configured successfully.')
                if enableChunkDataPayloads(cam=camera, cam_name=cam_name,
                        chunkDataToRetreive=['FrameID', 'Timestamp']):
                    print('Chunk data enabled\n')
                else:
                    raise Exception('Could not enable chunk data!')
            else:
                raise Exception('Could not configure buffer!')
        else:
            raise Exception('Could not configure gain!')
    else:
        raise Exception('Could not configure exposure!')

    if cam_params['disableGamma']:
        if disable_gamma(cam=camera, cam_name=cam_name):
            print('Gamma disabled successfully.')
        else:
            raise Exception('Could not disable gamma!')

    return cam_params


def StartGrabbing(camera):
    try:
        camera.BeginAcquisition()
        return True
    except PySpin.SpinnakerException as ex:
        print(f'Error: {ex}')
        return False
    except Exception as err:
        print(f'Exception in cam.py function StartGrabbing(camera): {err}')
        return False


def GrabFrame(camera, frameNumber, grabTimeOutInMilliseconds):
    image_result = camera.GetNextImage(grabTimeOutInMilliseconds)
    #  Ensure image completion
    if image_result.IsIncomplete():
        image_status = image_result.GetImageStatus()
        print(f'Image incomplete with image status {image_status} ...')
        raise ImageNotCompleteException('Image not complete', image_status)
    return image_result


def GetImageArray(grabResult, cam_params):
    return grabResult.GetNDArray()


def GetChunkData(grabResult):
    return grabResult.GetChunkData()


def GetTimeStamp(chunkData):
    return chunkData.GetTimestamp() * 1e-9


def GetFrameID(chunkData):
    return chunkData.GetFrameID()


def DisplayImage(cam_params, dispQueue, grabResult):
    if cam_params['pixelFormatInput'] != 'gray':
        # Convert to RGB
        img_converted = grabResult.Convert(PySpin.PixelFormat_RGB8, PySpin.HQ_LINEAR)

        # Get Numpy Array
        img = img_converted.GetNDArray()
    else:
        img = grabResult.GetNDArray()

    # Downsample image
    img = img[::cam_params["displayDownsample"], ::cam_params["displayDownsample"]]

    # Send to display queue
    dispQueue.append(img)


def ReleaseFrame(grabResult):
    grabResult.Release()


def CloseCamera(camera, cam_name):
    """Close camera after acquisition stops"""
    print(f'Closing {cam_name}... Please wait.')
    while True:
        try:
            try:
                # Close camera
                camera.EndAcquisition()
                camera.DeInit()
                del camera
                break

            except PySpin.SpinnakerException as ex:
                print(f'Error for camera {cam_name}: {ex}')
            except Exception as e:
                logging.error(f'Caught exception at cam.py CloseCamera for camera {cam_name}: {e}')
                break
        except KeyboardInterrupt:
            break


def CloseSystem(system, device_list):
    try:
        device_list.Clear()
        system.ReleaseInstance()
        print(f'Closed systems')
    except PySpin.SpinnakerException as ex:
        print(f'SpinnakerException at cam.py CloseSystem for {cam_name}: {ex}')
        print('passing from', __name__)
    except Exception as err:
        print(f'Exception at cam.py CloseSystem for {cam_name}: {err}')
