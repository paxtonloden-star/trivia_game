# Trivia Game

Dedicated Home Assistant trivia integration split cleanly from the mixed card-game project.

## Installation

### HACS custom repository

1. Open HACS in Home Assistant.
2. Open the menu in the top-right corner.
3. Choose **Custom repositories**.
4. Add this repository URL.
5. Select **Integration** as the category.
6. Install **Trivia Game**.
7. Restart Home Assistant.
8. Go to **Settings → Devices & services → Add integration**.
9. Search for **Trivia Game**.

## Repository structure

This repository follows the HACS integration layout:

- `custom_components/trivia_game/`
- `hacs.json`
- GitHub Actions for HACS validation and Hassfest

## Current features

- Dedicated trivia-only integration
- Host page and player page
- Join code and QR endpoint
- Live websocket updates
- Manual question entry
- Question queue
- JSON trivia-pack import
- Pack loading into queue
- Timed rounds
- Auto reveal and optional auto-next
- TTS provider and speaker targeting support in the runtime
- Optional player picture URL for avatar display

## Development notes

### Brand images

Home Assistant now supports custom integrations shipping their own brand images directly inside the integration folder. Add your brand files here:

- `custom_components/trivia_game/brand/icon.png`
- `custom_components/trivia_game/brand/logo.png`

Optional dark variants are also supported by Home Assistant.

### Validation

This repository includes:

- HACS validation workflow
- Hassfest workflow

## Planned next steps

- Host authentication/admin controls
- Better game-show styling and polish
- Multi-round pack session flow
- Better pack browsing/import UX
- Home Assistant entity-based avatars instead of URL-only pictures
