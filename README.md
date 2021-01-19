# OpcBridge
This is a server that implements a simple rendering engine controlled by a REST API. 
It controls a 512x3 array of RGB values which are submitted to an Open Pixel Control Server.
The original use case of this project is to interact with scanlime's Fadecandy controller for WS2811 pixels

# REST API Commands
## AbsoluteFade
Route: /absolutefade

Takes a selection of pixel indexes and fades them to a given RGB value over a given period of time

### GET
#### JSON Parameters
* rgb: (list, 3 integers) RGB value to fade selected indexes to
* indexes: (list, up to 512 integers) Which pixels to set
* fadetime: (integer) amount of seconds the fade will take

### PUT
No implementation

## RelativeFade
Route: /relativefade

Takes a selection of pixel indexes and increases or decreases their brightness a given amount relative to their current values

Note: This may cause unpredicatble behavior if called in the middle of another fade
### GET
### JSON Parameters
* magnitude: (integer) Signed value between 0 and 255 indicating how much brightness to fade up or down
* indexes: (list, up to 512 integers) Which pixels to adjust
* fadetime (integer) Amount of seconds the fade will take

### PUT
no implementation

## Multicommand
Route: /multicommand
A list of absolute fade commands to be executed simultaneously. Unlike AbsoulteFade, this can assign different rgb values to different pixels as well as different fade times. The implementation of this makes it much more efficent than sending several different AbsoluteFade commands simultaneously or in tight sequence.

### GET
### JSON Parameters
* commandlist (indexes, rgb, fadetime)
  * indexes: (list, up to 512 integers) Which pixels to adjust
  * rgb: (list, 3 integers) RGB value to fade selected indexes to
  * fadetime: (integer) amount of seconds the fade will take
### PUT
Not implemented

## Arbitration
Route: /arbitration

Stores the ip address and an ID string of the last device to explicity take control of the server. This value is used to negotiate who should be in control of the server. Automated routines should take arbitration at the start of their routine, and ask for arbitration before every subsequent cycle. Manual routines should submit an arbitration ID in order to interrupt any automated routines that are running. 

### GET
### JSON Parameters
* id: (string) A unique identifier for the routine or manual event taking control of the server. If the id and IP of the arbitration request match the stored value on the server, it will return True. If not, it will return False

### PUT
### JSON Parameters
* id: (string) A unique identifier for the routine or manual event taking control of the server. The server will store this value along with the IP of the requestor, overriding the previous value

## Pixels
Route: /pixels

Returns the a 512x3 array containing all current pixel values.

### GET
### JSON Parameters
This command takes no parameters

