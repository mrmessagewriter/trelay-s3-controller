# TRelay-S3-Controller promotion and launch checklist

This document contains the repository metadata, launch copy, and promotion checklist for sharing TRelay-S3-Controller with ESP32, MicroPython, LILYGO, and maker communities.

## Recommended GitHub repository description

Use this as the short repository description in GitHub's **About** section:

> MicroPython web and REST controller for the LILYGO T-Relay ESP32-S3 with relay scheduling, Wi-Fi, USB CDC-NCM, weather conditions, and persistent automation.

## Recommended GitHub topics

Recommended topics for this project:

```text
esp32
esp32-s3
micropython
lilygo
t-relay
relay-controller
iot
home-automation
rest-api
web-interface
wifi
usb-ncm
embedded
automation
scheduler
```

These should be entered under the repository's **About** section so the project appears in GitHub topic searches and related-project browsing.

## Social preview

A 1280×640 social preview image is stored at:

```text
docs/images/social-preview.png
```

To use it as the GitHub social preview:

1. Open the repository on GitHub.
2. Choose **Settings**.
3. Open **General**.
4. Find **Social preview**.
5. Upload `docs/images/social-preview.png`.

The same image can be reused when posting the project elsewhere.

## Suggested Reddit / forum launch post

### Title

**I built a MicroPython web + REST controller for the LILYGO T-Relay ESP32-S3, including optional USB networking**

### Body

I have been working on an open-source controller for the six-relay LILYGO T-Relay ESP32-S3.

It runs entirely on MicroPython and provides a browser UI plus REST API for all six relays. It also has recurring schedules, persistent event logging, optional weather-based conditions, NTP time sync, and a versioned firmware deployment system.

One of the more unusual parts is an optional custom MicroPython runtime that exposes the ESP32-S3 as a **USB CDC-NCM network adapter**. That lets the same HTTP UI and REST API work directly over a USB cable without needing Wi-Fi.

The application still works over normal Wi-Fi if you do not need USB networking.

Project:
https://github.com/mrmessagewriter/trelay-s3-controller

I would especially be interested in feedback from people using MicroPython on ESP32-S3 boards, LILYGO relay boards, or USB networking on embedded devices.

## Short announcement

Useful for Discord, Mastodon, Bluesky, forum signatures, or smaller communities:

> TRelay-S3-Controller is an open-source MicroPython web/REST controller for the LILYGO T-Relay ESP32-S3. It supports six relays, schedules, persistent logging, optional weather rules, Wi-Fi, and an optional USB CDC-NCM network interface. https://github.com/mrmessagewriter/trelay-s3-controller

## MicroPython-focused post

### Title

**MicroPython + ESP32-S3 + USB CDC-NCM: a working relay-controller project**

### Body

I have been building TRelay-S3-Controller for the LILYGO T-Relay ESP32-S3 and ended up needing direct network access over USB in addition to Wi-Fi.

The project now has a custom MicroPython runtime with `network.USBD_NCM`, a private `172.31.77.0/24` USB management network, and the same Microdot HTTP server serving both Wi-Fi and USB.

I wrote up the implementation and build path here:

https://github.com/mrmessagewriter/trelay-s3-controller/blob/main/docs/USB_CDC_NCM_ON_ESP32_S3.md

The full project is here:

https://github.com/mrmessagewriter/trelay-s3-controller

Feedback on the ESP32/lwIP/TinyUSB side is welcome.

## LILYGO / hardware-focused post

### Title

**Open-source web controller firmware for the LILYGO T-Relay ESP32-S3**

### Body

I built an open-source MicroPython controller specifically for the six-relay LILYGO T-Relay ESP32-S3.

It includes:

- browser control for all six relays;
- REST API;
- recurring schedules;
- persistent event logs;
- optional weather conditions;
- Wi-Fi;
- optional USB CDC-NCM networking;
- build and upload tools for versioned firmware packages.

Repository and screenshots:

https://github.com/mrmessagewriter/trelay-s3-controller

## Places worth sharing

Prioritize communities where the project solves a problem people already discuss:

- ESP32 communities and forums;
- MicroPython forums and communities;
- LILYGO user communities;
- r/esp32;
- r/MicroPython;
- maker and embedded-systems Discord servers;
- Hackaday.io project pages;
- home-automation communities when presenting the generic REST/relay use case;
- embedded networking communities when presenting the USB CDC-NCM work.

Avoid posting the exact same message everywhere. Lead with the part most relevant to each community.

## Article ideas

The USB networking work gives the project a useful technical angle beyond the relay-controller use case. Possible article titles:

- **USB CDC-NCM networking with MicroPython on ESP32-S3**
- **Using one Microdot HTTP server over Wi-Fi and USB on ESP32-S3**
- **Building a private USB management network for an ESP32-S3**
- **A versioned MicroPython firmware deployment system using a read-only ZIP VFS**
- **Designing a standalone REST relay controller on the LILYGO T-Relay ESP32-S3**

The first article is already available in this repository:

[USB CDC-NCM networking on MicroPython and ESP32-S3](USB_CDC_NCM_ON_ESP32_S3.md)

## Launch checklist

- [x] Visitor-focused README summary.
- [x] Project screenshot near the top of the README.
- [x] Animated relay-control demo.
- [x] Quick Start instructions.
- [x] Social-preview image generated.
- [x] Current application release notes improved.
- [x] Future application release notes improved in GitHub Actions.
- [x] USB CDC-NCM technical article added.
- [x] GitHub traffic measurement plan documented.
- [ ] Set the GitHub repository description from the text above.
- [ ] Add the recommended GitHub topics.
- [ ] Select `docs/images/social-preview.png` as the GitHub Social Preview.
- [ ] Publish the project in at least two relevant technical communities.
- [ ] Publish or cross-post the USB CDC-NCM article outside GitHub.

## What to watch after posting

Use GitHub's **Insights → Traffic** page. It reports the recent traffic window, including views, unique visitors, clones, referring sites, and popular repository content.

The default `GITHUB_TOKEN` supplied to GitHub Actions cannot access the repository traffic API for this repository, so this project intentionally does not include a scheduled traffic workflow that would fail without a separate personal access token.

When evaluating promotion, focus on:

- unique visitors rather than raw page views;
- which referring sites actually send traffic;
- which repository pages people visit most;
- clones after an announcement;
- stars and issues as secondary signals of real interest.

A community that sends 30 visitors who clone the project is more valuable than one that sends hundreds of low-intent clicks.
