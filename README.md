# toolbox

My personal toolbox of utility scripts

[Browse the toolbox](https://pisaucer.github.io/toolbox/)

`toolbox.py` is a cross-platform CLI and terminal UI for browsing, downloading, verifying, and running utility scripts from the toolbox. The toolbox is a searchable collection of scripts that I use for various tasks, and it is backed by a remote manifest that lists the available scripts and their SHA-256 hashes for verification.

## Requirements

* Python 3.9 or newer
* `rich`

## Features

* Browse and search the toolbox website or the command line interface.
* Interactive terminal UI for browsing available scripts.
* Search scripts by name, ID, description, language, category, or tags.
* View script descriptions, usage examples, download URLs, and checksums.
* Download one or multiple scripts directly from the command line.
* Verify every downloaded script against its SHA-256 checksum.
* Run verified Python and shell scripts directly from the TUI.
* Check for newer Toolbox releases with `toolbox --version`.
* Works on macOS, Linux, and Windows with python3 installed.

## Install

### Homebrew (macOS)

On macOS, install with Homebrew:

```bash
brew tap PiSaucer/homebrew-tap
brew install PiSaucer/tap/toolbox
```

### Python Package (`pipx`)

Recommended when installing Toolbox as an isolated Python CLI:

```bash
pipx install pisaucer-toolbox
toolbox --version
```

### Python Package (`pip`)

```bash
python3 -m pip install pisaucer-toolbox
```

### Python Package (`uv`)

```bash
uv tool install pisaucer-toolbox
toolbox --version
```

### macOS / Linux installer

```bash
curl -fsSL https://pisaucer.github.io/toolbox/install.sh | sh
```

## Build from source

Build a wheel:

```bash
python3 -m build
pipx install ./dist/pisaucer_toolbox-*.whl
toolbox --version
```

```bash
pipx install .
```

```bash
./install.sh
```

## Uninstall

If you used the macOS/Linux installer, run:

```bash
./uninstall.sh
```

Use the matching package manager if `toolbox` was installed as a package:

```bash
brew uninstall toolbox
pipx uninstall pisaucer-toolbox
uv tool uninstall pisaucer-toolbox
python3 -m pip uninstall pisaucer-toolbox
```

## Links

* [Toolbox Website](https://pisaucer.github.io/toolbox/)
* [GitHub Repository](https://github.com/PiSaucer/toolbox)
* [Releases](https://github.com/PiSaucer/toolbox/releases)
* [Issues](https://github.com/PiSaucer/toolbox/issues)
* [PyPI](https://pypi.org/project/pisaucer-toolbox/)

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for more information.
