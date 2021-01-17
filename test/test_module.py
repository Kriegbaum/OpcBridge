from opcBridge import makeEightBit, rgbSetBrightness
def test_makeEightBit():
    assert makeEightBit(3666) == 255

def test_rgbSetBrightness():
    newRGB = rgbSetBrightness(255, [1,1,1])
    assert newRGB == [255,255,255]
