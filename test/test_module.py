import opcBridge

def test_makeEightBit():
    assert opcBridge.makeEightBit(3666) == 255

def test_rgbSetBrightness():
    assert opcBridge.rgbSetBrightness(255, [1,1,1]) == [255,255,255]
    assert opcBridge.rgbSetBrightness(255, [0,0,0]) == [0,0,0]
    assert opcBridge.rgbSetBrightness(0, [255,255,255]) == [0,0,0]

def test_brightnessChange():
    assert opcBridge.brightnessChange([128,128,128], 0) == [128,128,128]
    assert opcBridge.brightnessChange([128,128,128], 255) == [255,255,255]
    assert opcBridge.brightnessChange([50,50,50], -128) == [1,1,1]

def test_getLocalIP():
    assert type(opcBridge.getLocalIP()) == str

def test_PSU():
    psu = opcBridge.PSU('127.0.0.1', 1)
    assert psu.checkPixels([[0,0,0]] * 512) == False
    assert psu.checkPixels(([[0,0,0]] * 512) + [[0,0,1]]) == True

def test_renderer():
    renderer = opcBridge.Renderer(16)
    fadeTime = 5
    indexes = [0]
    rgb = [255,255,255]
    renderer.absoluteFade(rgb, indexes, fadeTime)
    assert renderer.remaining[indexes[0]] == fadeTime * renderer.frameRate
    assert renderer.endVals[0][0] == 255
