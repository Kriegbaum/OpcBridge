import opc
import time
import os
import socket
import json
import threading
import queue
import datetime
import numpy as np
import yaml
from flask import Flask, request
from flask_restful import Resource, Api, reqparse
import logging
import requests

############################SUPPORT FUNCTIONS###################################
def pixelsToJson(npArray):
    lstOut = []
    for i in npArray:
        lstOut.append([int(i[0]), int(i[1]), int(i[2])])
    return lstOut

def makeEightBit(value):
    return min(255, max(0, int(value)))

def rgbSetBrightness(setBri, rgb):
    currentBri = max(rgb)
    if currentBri == 0:
        ratio = 0
    else:
        ratio = setBri / currentBri
    rgbOut = [rgb[0] * ratio, rgb[1] * ratio, rgb[2] * ratio]
    return rgbOut

def brightnessChange(rgb, magnitude):
    '''Will take an RGB value and a brigtness change and spit out what its final value should be'''
    currentBri = max(rgb)
    if currentBri:
        newBri = currentBri + magnitude
        newBri = min(255, max(0, int(newBri)))
        if not newBri:
            newBri = 1
        if currentBri == newBri:
            return rgb
        rgbOut = rgbSetBrightness(newBri, rgb)
        return rgbOut
    else:
        return rgb

def bridgeValues(totalSteps, start, end):
    '''Generator that creates interpolated steps between a start and end value'''
    newRGB = start
    diffR = (end[0] - start[0]) / float(totalSteps)
    diffG = (end[1] - start[1]) / float(totalSteps)
    diffB = (end[2] - start[2]) / float(totalSteps)
    for i in range(totalSteps - 1):
        newRGB = [newRGB[0] + diffR, newRGB[1] + diffG, newRGB[2] + diffB]
        yield [int(newRGB[0]), int(newRGB[1]), int(newRGB[2])]
    yield end
################################################################################

class PSU:
    def __init__(self, ip, port, index):
        self.ip = ip
        self.port = port
        self.index = index

    def switch(self, state):
        '''Switch relay attached to lighting PSU'''
        try:
            params = {'index': self.index, 'state': self.state}
            requests.get('http://' + ip + ':' + str(port) + '/switch', json=params, timeout=4)
            self.state = state
        except:
            print('Failed to connect to relay processor')

    def checkPixels(self, pixels):
        '''Crawl down pixel array, if any value is above 0 return true
        Used in conjunction with self.switch to kill power to PSU if lights are off'''
        for pix in pixels:
            for color in pix:
                if color > 0:
                    return True
        return False

    def update(self, pixels):
        '''If pixel array has no lights on, kill its associated PSU'''
        if self.checkPixels(pixels):
            print('Spinning up PSU')
            self.switch(True)
        else:
            print('Killing PSU')
            self.switch(False)


class Renderer:
    def __init__(self):
        #Current value of pixels being submitted to opc
        self.pixels = np.zeros((512, 3), dtype='float32')
        #Differential array: stores difference between this frame and the next
        self.diff = diff = np.zeros((512, 3), dtype='float32' )
        #End values: where the final frame should end up
        self.endVals = np.zeros((512, 3), dtype='float32')
        #Remaining number of frames for each pixel
        self.remaining = np.zeros((512), dtype='uint16')

        #Used to sleep thread when there is no rendering to be done
        self.clockerActive = threading.Event()
        #Queue of commands to be executed
        #API handler thread produces commands, Render Loop consumes them
        self.commands = queue.Queue(maxsize=100)
        #TODO: Make framerate and opcClient ip configurable
        self.frameRate = 16
        self.opcClient = opc.Client('localhost:7890')
        self.arbitration = [False, '127.0.0.1']
        self.renderLoop = threading.Thread(target=self.render)
        self.renderLoop.daemon = True

    def absoluteFade(self, rgb, indexes, fadeTime):
        '''Take pixels marked in indexes and fade them to value in rgb over
        fadeTime amount of time'''
        #If the fadeTime is 0, we still want at least 2 frames
        #If only one frame, the interpolation engine will produce slow fade
        if not fadeTime:
            fadeTime = 2 / frameRate
        frames = int(fadeTime * self.frameRate)
        for i in indexes:
            self.remaining[i] = frames
            for c in range(3):
                self.diff[i][c] = (rgb[c] - pixels[i][c]) / frames
            self.endVals[i] = rgb

    def multiCommand(self, commandList):
        '''Multicommand format: [indexes, rgb value, fadetime]
        allows for multiple different pixels to be set to multiple different values
        this is more efficent than stringing individual commands together'''
        for x in commandList:
            #Which pixels are being controlled?
            indexes = x[0]
            #How much time does it take to complete?
            frames = int(x[2] * self.frameRate)
            if not frames:
                frames = 2
            #What color are we fading to?
            rgb = x[1]
            for i in indexes:
                self.remaining[i] = frames
                for c in range(3):
                    self.diff[i][c] = (rgb[c] - self.pixels[i][c]) / frames
                self.endVals[i] = rgb

    def relativeFade(self, magnitude, indexes, fadeTime):
        '''fade value up or down relative to current pixel values'''
        commandList = []
        for i in indexes:
            endVal = brightnessChange(self.pixels[i], magnitude)
            commandList.append([[i], endVal, fadeTime])
        self.multiCommand(commandList)

    def render(self, PSU):
        '''Primary rendering loop, takes commands from API handler at start and
        submits frames at end'''
        print('Initiating Render Loop...')
        checkPSU = False
        while True:
            now = time.perf_counter()
            while not self.commands.empty():
                newCommand, args = self.commands.get()
                checkPSU = True
                try:
                    newCommand(*args)
                except Exception as e:
                    print('Command failed!')
                    logError(str(e))

            anyRemaining = False
            for pix in range(512):
                if not self.remaining[pix]:
                    pass
                elif self.remaining[pix] > 1:
                    for i in range(3):
                        self.pixels[pix][i] += self.diff[pix][i]
                    self.remaining[pix] -= 1
                    anyRemaining = True
                elif self.remaining[pix] == 1:
                    self.pixels[pix] = self.endVals[pix]
                    self.remaining[pix] -= 1
                    anyRemaining = True
            if checkPSU:
                PSU.update(self.pixels)
                checkPSU = False

            try:
                self.opcClient.put_pixels(self.pixels)
            except Exception as e:
                print('Unable to contact opc Client')
            cycleTime = time.perf_counter() - now
            time.sleep(max((1 / self.frameRate) - cycleTime, 0))
            if not anyRemaining:
                PSU.update(self.pixels)
                if self.commands.empty():
                    self.clockerActive.clear()
                    print('Sleeping render loop...')
            self.clockerActive.wait()

class ApiHandler:
    def __init__(self, localIp, port):
        self.fetcher = Flask(__name__)
        self.api = Api(self.fetcher)
        self.parser = reqparse.RequestParser()

    #########################VARIOUS COMMAND FIELDS#########################
        self.parser.add_argument('fadetime', type=float, help='How long will this fade take?')
        self.parser.add_argument('indexes', type=json.loads, help='Which pixels are targeted')
        self.parser.add_argument('id', type=str, help='Arbtration ID')
        self.parser.add_argument('ip', type=str, help='IP address of client')
        self.parser.add_argument('rgb', type=json.loads, help='Target color')
        self.parser.add_argument('magnitude', type=float, help='Size of fade')
        self.parser.add_argument('commandlist', type=json.loads, help='List of commands for a multicommand')

        self.api.add_resource(self.Pixels, '/pixels')
        self.api.add_resource(self.Arbitration, '/arbitration')
        self.api.add_resource(self.AbsoluteFade, '/absolutefade')
        self.api.add_resource(self.MultiCommand, '/multicommand')
        self.api.add_resource(self.RelativeFade, '/relativefade')

        self.localIp = localIp
        self.port = port

    ###################COMMAND TYPE HANDLING########################################
    class Pixels(Resource):
        def get(self):
            '''Gives the entire pixel array back to the client as a 512 * 3 array'''
            print('\nSending pixels to %s \n' % request.remote_addr)
            message = pixelsToJson(pixels)
            return message

    class Arbitration(Resource):
        def put(self):
            args = parser.parse_args()
            id = args['id']
            ip = request.remote_addr
            print('\nGiving arbitration to %s from %s\n' % (id, ip))
            arbitration[0] = id
            arbitration[1] = ip

        def get(self):
            args = parser.parse_args()
            id = args['id']
            ip = request.remote_addr
            print('\nSending arbitration to %s for %s\n' % (ip, id))
            if id != arbitration[0]:
                return False
            elif ip != arbitration[1]:
                return False
            else:
                return True

    class AbsoluteFade(Resource):
        '''Is given a color to fade to, and executes fade'''
        def get(self):
            args = parser.parse_args()
            fadeTime = args['fadetime']
            rgb = args['rgb']
            indexes = args['indexes']
            commands.put((absoluteFade, [rgb, indexes, fadeTime]))
            clockerActive.set()

    class MultiCommand(Resource):
        '''Is given a list of indexes, associated values and fade times
        executes them all in one action. This is much more efficent than
        several absoluteFade commands strung together'''
        def get(self):
            args = parser.parse_args()
            commandList = args['commandlist']
            commands.put((multiCommand, [commandList]))
            clockerActive.set()

    class RelativeFade(Resource):
        '''Is given a brightness change, and alters the brightness, likely unpredicatable
        behavior if called in the middle of another fade'''
        def get(self):
            args = parser.parse_args()
            indexes = args['indexes']
            magnitude = args['magnitude']
            fadeTime = args['fadetime']
            commands.put((relativeFade, [magnitude, indexes, fadeTime]))
            clockerActive.set()

    def launch(self):
        self.fetcher.run(host=self.localIP, port=self.port, debug=False)


if __name__ == '__main__':
    #########################LOAD IN USER CONFIG####################################
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'opcConfig.yml')) as f:
        configFile = f.read()
    configs = yaml.safe_load(configFile)

    ##########################GET LOCAL IP##########################################
    ipSock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ipSock.connect(('10.255.255.255', 1))
        localIP = ipSock.getsockname()[0]
        print('Local IP set to', localIP)
    except Exception as e:
        print(e)
        print('Local IP detection failed, listening on localhost')
        localIP = '127.0.0.1'
    ipSock.close()

    #########################CONTROL OBJECT DEFINITIONS#############################
    pixels = np.zeros((512, 3), dtype='float32')
    diff = np.zeros((512, 3), dtype='float32' )
    endVals = np.zeros((512, 3), dtype='float32')
    remaining = np.zeros((512), dtype='uint16')

    clockerActive = threading.Event()

    commands = queue.Queue(maxsize=100)
    frameRate = 16
    FCclient = opc.Client('localhost:7890')
    arbitration = [False, '127.0.0.1']

    ##################SERVER LOGGING AND REPORTING FUNCTIONS########################
    def logError(err):
        print(err)
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'opcBridge-log.txt'), 'a') as logFile:
            logFile.write(err)
            logFile.write('\n')

    bootMsg = 'Server booted at ' + str(datetime.datetime.now()) + '\n'
    logError(bootMsg)


    clocker = threading.Thread(target=clockLoop)

    #Test pattern to indicate server is up and running
    testPatternOff = np.zeros((512, 3))
    testPatternRed = np.full((512, 3), [64,0,0])

    FCclient.put_pixels(testPatternRed)
    FCclient.put_pixels(testPatternRed)
    time.sleep(.5)
    FCclient.put_pixels(testPatternOff)
    FCclient.put_pixels(testPatternOff)
    time.sleep(.5)
    FCclient.put_pixels(testPatternRed)
    FCclient.put_pixels(testPatternRed)
    time.sleep(.5)
    FCclient.put_pixels(testPatternOff)
    FCclient.put_pixels(testPatternOff)

    del testPatternOff
    del testPatternRed

    #Initiate server
    clocker.daemon = True
    clocker.start()
    fetcher.run(host=localIP, port=8000, debug=FLASK_DEBUG)
