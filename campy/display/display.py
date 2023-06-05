"""
"""
import sys
import time
import logging
import numpy as np
import matplotlib as mpl
mpl.use('Qt5Agg') # disregard qtapp warning...
import matplotlib.pyplot as plt

def DrawFigure(cam_name, n_cam):
	mpl.rcParams['toolbar'] = 'None'

	figure = plt.figure(cam_name)
	ax = plt.axes([0,0,1,1], frameon=False)

    # display the windows in non-overlapping positions
	mngr = plt.get_current_fig_manager()
	width = 640
	# distribute the windows in a row on the screen
	# TODO check that the windows will actually fit on the screen
	x = n_cam*width + 25
	# args are x, y, width, height
	mngr.window.setGeometry(x, 25, width, 480)

	plt.axis('off')
	plt.autoscale(tight=True)
	plt.ion()

	imageWindow = ax.imshow(np.zeros((1,1,3), dtype='uint8'),
		interpolation='none')

	figure.canvas.draw()
	plt.show(block=False)

	return figure, imageWindow

def DisplayFrames(cam_params, dispQueue):
	if not (sys.platform=='win32' and cam_params['cameraMake'] == 'basler'):
		figure, imageWindow = DrawFigure(cam_params['cameraName'],
		                                 cam_params['n_cam'])
		while(True):
			try:
				if dispQueue:
					img = dispQueue.popleft()
					# ToDo: Find a way to plot in the main thread
					try:
						imageWindow.set_data(img)
						figure.canvas.draw()
						figure.canvas.flush_events()
					except Exception as e:
						logging.error(f'Caught exception: {e}')
				else:
					time.sleep(0.01)
			except KeyboardInterrupt:
				break
		plt.close(figure)
