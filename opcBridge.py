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
def getLocalIP():
    '''Get our IP address'''
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
    return localIP

def pixelsToJson(npArray):
    '''numPy arrays do not cleanly serialize. This takes our numPy array and converts
    to a standard python list so that we can easily dump it as JSON'''
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

################################################################################

class PSU:
    def __init__(self, ip, index, port=8001):
        self.ip = ip
        self.port = port
        self.index = index

    def switch(self, state):
        '''Switch relay attached to lighting PSU'''
        try:
            params = {'index': self.index, 'state': state}
            requests.get('http://' + self.ip + ':' + str(self.port) + '/switch', json=params, timeout=3)
        except Exception as e:
            print('Failed to connect to relay processor')
            print(e)

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
    def __init__(self, frameRate, PSU=False):
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
        self.frameRate = frameRate
        self.opcClient = opc.Client('localhost:7890')
        self.renderLoop = threading.Thread(target=self.render)
        self.renderLoop.daemon = True
        self.PSU = PSU

    def absoluteFade(self, rgb, indexes, fadeTime):
        '''Take pixels marked in indexes and fade them to value in rgb over
        fadeTime amount of time'''
        #If the fadeTime is 0, we still want at least 2 frames
        #If only one frame, the interpolation engine will produce slow fade
        if not fadeTime:
            fadeTime = 2 / self.frameRate
        frames = int(fadeTime * self.frameRate)
        for i in indexes:
            self.remaining[i] = frames
            for c in range(3):
                self.diff[i][c] = (rgb[c] - self.pixels[i][c]) / frames
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

    def executeCommands(self):
        '''Take all commands out of command queue and execute them'''
        while not self.commands.empty():
            newCommand, args = self.commands.get()
            try:
                newCommand(*args)
            except Exception as e:
                print('Command failed!')
                logError(str(e))

    def render(self):
        '''Primary rendering loop, takes commands from API handler at start and
        submits frames at end'''
        print('Initiating Render Loop...')
        checkPSU = False
        while True:
            now = time.perf_counter()
            if not self.commands.empty():
                checkPSU = True
                self.executeCommands()
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
            if self.PSU and checkPSU:
                self.PSU.update(self.pixels)
                checkPSU = False

            try:
                self.opcClient.put_pixels(self.pixels)
            except Exception as e:
                print('Unable to contact opc Client')
            cycleTime = time.perf_counter() - now
            time.sleep(max((1 / self.frameRate) - cycleTime, 0))
            if not anyRemaining:
                if self.PSU:
                    self.PSU.update(self.pixels)
                if self.commands.empty():
                    self.clockerActive.clear()
                    print('Sleeping render loop...')
            self.clockerActive.wait()


if __name__ == '__main__':
    #########################LOAD IN USER CONFIG####################################
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'opcConfig.yml')) as f:
        configFile = f.read()
    configs = yaml.safe_load(configFile)


    ##################SERVER LOGGING AND REPORTING FUNCTIONS########################
    def logError(err):
        print(err)
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'opcBridge-log.txt'), 'a') as logFile:
            logFile.write(err)
            logFile.write('\n')

    bootMsg = 'Server booted at ' + str(datetime.datetime.now()) + '\n'
    logError(bootMsg)

    psu = PSU(configs['PSUs']['ip'], configs['PSUs']['index'], port=configs['PSUs']['port'])
    renderer = Renderer(configs['framerate'], PSU=psu)


    flaskServer = Flask(__name__)
    api = Api(flaskServer)

    localIP = getLocalIP()
    port = 8000
    arbitration = [False, '127.0.0.1']
    parser = reqparse.RequestParser()

    #########################VARIOUS COMMAND FIELDS#########################
    parser.add_argument('fadetime', type=float, help='How long will this fade take?')
    parser.add_argument('indexes', type=json.loads, help='Which pixels are targeted')
    parser.add_argument('id', type=str, help='Arbtration ID')
    parser.add_argument('ip', type=str, help='IP address of client')
    parser.add_argument('rgb', type=json.loads, help='Target color')
    parser.add_argument('magnitude', type=float, help='Size of fade')
    parser.add_argument('commandlist', type=json.loads, help='List of commands for a multicommand')

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
            renderer.commands.put((renderer.absoluteFade, [rgb, indexes, fadeTime]))
            renderer.clockerActive.set()

    class MultiCommand(Resource):
        '''Is given a list of indexes, associated values and fade times
        executes them all in one action. This is much more efficent than
        several absoluteFade commands strung together'''
        def get(self):
            args = parser.parse_args()
            commandList = args['commandlist']
            renderer.commands.put((renderer.multiCommand, [commandList]))
            renderer.clockerActive.set()

    class RelativeFade(Resource):
        '''Is given a brightness change, and alters the brightness, likely unpredicatable
        behavior if called in the middle of another fade'''
        def get(self):
            args = parser.parse_args()
            indexes = args['indexes']
            magnitude = args['magnitude']
            fadeTime = args['fadetime']
            renderer.commands.put((renderer.relativeFade, [magnitude, indexes, fadeTime]))
            renderer.clockerActive.set()

    api.add_resource(Pixels, '/pixels')
    api.add_resource(Arbitration, '/arbitration')
    api.add_resource(AbsoluteFade, '/absolutefade')
    api.add_resource(MultiCommand, '/multicommand')
    api.add_resource(RelativeFade, '/relativefade')

    psu.switch(True)

    #Test pattern to indicate server is up and running
    testPatternOff = np.zeros((512, 3))
    testPatternRed = np.full((512, 3), [64,0,0])

    renderer.opcClient.put_pixels(testPatternRed)
    renderer.opcClient.put_pixels(testPatternRed)
    time.sleep(.5)
    renderer.opcClient.put_pixels(testPatternOff)
    renderer.opcClient.put_pixels(testPatternOff)
    time.sleep(.5)
    renderer.opcClient.put_pixels(testPatternRed)
    renderer.opcClient.put_pixels(testPatternRed)
    time.sleep(.5)
    renderer.opcClient.put_pixels(testPatternOff)
    renderer.opcClient.put_pixels(testPatternOff)
    del testPatternOff
    del testPatternRed


    renderer.renderLoop.start()
    flaskServer.run(host=localIP, port=port, debug=False)
