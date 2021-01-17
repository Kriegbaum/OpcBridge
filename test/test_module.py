from opcBridge import makeEightBit, rgbSetBrightness, brightnessChange, psuCheck
def test_makeEightBit():
    assert makeEightBit(3666) == 255

def test_rgbSetBrightness():
    assert rgbSetBrightness(255, [1,1,1]) == [255,255,255]
    assert rgbSetBrightness(255, [0,0,0]) == [0,0,0]
    assert rgbSetBrightness(0, [255,255,255]) == [0,0,0]

def test_brightnessChange():
    assert brightnessChange([128,128,128], 0) == [128,128,128]
    assert brightnessChange([128,128,128], 255) == [255,255,255]
    assert brightnessChange([50,50,50], -128) == [1,1,1]

def test_psuCheck():
    assert psuCheck([[0,0,0]] * 512) == False
    assert psuCheck(([[0,0,0]] * 511) + [[0,0,1]]) == True
