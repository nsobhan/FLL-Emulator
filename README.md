# FFL Emulator

A virtual LEGO® Education SPIKE™ Prime hub for practising without the robot. It runs on a Mac and
shows a simulated robot driving on a mat in the browser.

- **Connect the real SPIKE app** (https://spike.legoeducation.com) over Bluetooth. Press Play
  and the program runs on the virtual robot.
- **Open `.llsp3` project files** without the app. Word Block programs run with each block
  lighting up as it runs, so kids can see what their code does.
- **Watch it work:** the robot moves on the mat with a trail. The page also shows the 5×5 light
  matrix, live values for ports A–F, a plain-language "what the robot is doing" feed, and the
  console.

This is an independent project and is not made, endorsed or supported by the LEGO Group.

## Try it in the browser

**https://nsobhan.github.io/FFL-Emulator/** opens the browser version. Drop in a `.llsp3`
Word Blocks project and watch the robot run it, block by block. Everything runs on your own
computer, and project files aren't uploaded anywhere. It's the `web/` folder: the same robot
simulator and Word Blocks interpreter, ported to JavaScript. Connecting the real SPIKE app over
Bluetooth, and running Python projects, need the Mac version below.

## Setup (macOS)

```bash
brew install micropython
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

If pip is set up to use a private package index, add `--index-url https://pypi.org/simple`.

## Start

Double-click **`Start Virtual Hub.command`**. It opens in Terminal, which macOS needs to grant
Bluetooth access. Allow Bluetooth the first time. The robot view opens at http://localhost:8765.

```bash
.venv/bin/python run.py            # Bluetooth hub + robot view
.venv/bin/python run.py --no-ble   # robot view only (project files and samples)
```

## Connecting the SPIKE app (on another laptop)

The SPIKE web app only lists hubs that advertise LEGO's manufacturer data, and a Mac can't
advertise that. The small Chrome extension in `laptop-extension/` (also zipped as
`show-virtual-hub-extension.zip`) adds a scan filter so the virtual hub, **Sim Hub**, appears too.
Real hubs still show up as usual.

1. Copy the extension folder to the laptop. In Chrome, open `chrome://extensions`, turn on
   Developer mode, choose **Load unpacked**, and pick `laptop-extension`.
2. Open the SPIKE app in Chrome, click **Connect**, choose Bluetooth, and pick **Sim Hub**.
3. Build a program and press **Play**.

To test once without installing it, paste `laptop-extension/show-virtual-hub.js` into the SPIKE
tab's DevTools console before clicking Connect.

## Trying projects without the app

On the **Try without the app** tab, drop a `.llsp3` file (in the SPIKE app: File → Save to your
device) or open a `.py` file, then click **Run project**. There are also sample Python programs.

## How it works

| Part | File |
| --- | --- |
| SPIKE Prime BLE protocol (COBS framing, messages) | `spikehub/protocol.py` |
| Bluetooth peripheral (CoreBluetooth via `bless`) | `spikehub/ble.py` |
| Hub message handling, uploads, program start/stop | `spikehub/service.py` |
| Robot, mats, motors and sensors simulation | `spikehub/world.py` |
| hub OS 3 Python API (`hub`, `motor`, `motor_pair`, sensors, …) | `spikehub/runtime.py` |
| Runs compiled `.mpy` programs from the app in MicroPython | `spikehub/mpruntime.py`, `spikehub/mp/` |
| Word Block engine for compiled block programs (`scratch`) | `spikehub/mp/scratch.py` |
| `.llsp3` reader and Word Blocks interpreter | `spikehub/blocks.py` |
| Robot view | `spikehub/static/index.html`, `spikehub/web.py` |
| Browser version (GitHub Pages) | `web/` |

The app compiles Word Blocks and Python to MicroPython bytecode. The emulator runs that bytecode
in real MicroPython, with stand-in hub modules that forward each call to the simulator.

Things to know:

- When a program uses a motor or sensor on a different port, the simulated robot rearranges
  itself to match.
- Programs keep running after their last block, like on the hub, until Stop is pressed.
- Blocks the simulator doesn't support yet are reported in the feed. The rest of the program
  keeps going.

## Tests

```bash
.venv/bin/python -m unittest discover tests
```

## Credits

The SPIKE Prime BLE protocol and the COBS framing code follow LEGO Education's published
[spike-prime-docs](https://github.com/LEGO/spike-prime-docs) (Apache License 2.0).
LEGO, the LEGO logo and SPIKE are trademarks of the LEGO Group.
