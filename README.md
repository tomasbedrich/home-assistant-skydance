# Overview

A Home Assistant integration for communication with Skydance lighting Wi-Fi relay.

<a href="https://www.buymeacoffee.com/tomasbedrich" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 30px !important;width: 106px !important;" ></a>

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)

Based on [skydance](https://github.com/tomasbedrich/skydance) Python library.


## Usage

1. Plug in your [Skydance Wi-Fi relay](http://www.iskydance.com/index.php?c=product_show&a=index&id=810).
   Set up its Wi-Fi connection so that you are able to `ping` it from both: a) Home Assistant, b) your mobile phone. 
2. Install the [official SkySmart Android application](https://play.google.com/store/apps/details?id=com.lxit.wifirelay&hl=cs&gl=US).
3. Inside the app: setup Zone names, types, pair the physical LED controllers.
   ([link to the manual](http://www.iskydance.com/uploads/goods_file/WiFi-Relay.pdf))
   Verify everything works using the app.
4. Go to Home Assistant.
   Install this integration (see below).
5. Set up the integration in Configuration > Integrations > Add Integration.
6. During the setup, enter the Wi-Fi relay IP configured in step 1.
   The integration discovers Zones configured in step 3 automatically.
7. Enjoy.


## Installation

### HACS
This install method is **preferred** since it allows automatic updates in the future.

Install by searching for _Skydance_ integration in [HACS](https://hacs.xyz/).

### Manual
1. [Download an integration](https://github.com/tomasbedrich/home-assistant-skydance/archive/master.zip).
2. Copy the folder `custom_components/skydance` from the zip to your config directory.
3. Restart Home Assistant.


## Known issues / limitations

- The integration does not know what is the current state of the lights.
  It is [technically not possible](https://github.com/tomasbedrich/home-assistant-skydance/issues/3#issuecomment-752373154).
  Therefore, "assumed state" light type is used, which results in rendering on/off buttons in Lovelace UI, instead of a toggle switch.
  If you plan to controll lights _from Home Assistant only_,
  you may want to "customize all lights in `skydance` domain to have `assumed_state: false`"
  ([link to the docs](https://www.home-assistant.io/docs/configuration/customizing-devices/#assumed_state)),
  which results in showing toggle switches instead.
- The Wi-Fi relay is able to process at most N commands per second (sequentially).
  This can be an issue for example when activating a Scene containing multiple Zones.
  Currently, [this is addresed](https://github.com/tomasbedrich/home-assistant-skydance/commit/031b837a745aed3ad805c9305fbd347ea70b3cf9)
  by adding `sleep(X)` between each command sent.
  Despite that, the relay is sometimes slower than expected resulting in some commands not being processed.
  Should this happen to you, please report an issue so that we can experimetally set the right `sleep` length.
