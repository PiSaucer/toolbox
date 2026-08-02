# toolbox

My personal toolbox of utility scripts

[Browse the toolbox](https://pisaucer.github.io/toolbox/)

## Install

On macOS, install with Homebrew:

```bash
brew tap PiSaucer/homebrew-tap
brew install PiSaucer/tap/toolbox
```

```bash
python3 -m pip install pisaucer-toolbox
```

```bash
pipx install pisaucer-toolbox
toolbox --version
```

```bash
uv tool install pisaucer-toolbox
toolbox --version
```

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

Use the matching package manager if toolbox was installed as a package:

```bash
brew uninstall toolbox
pipx uninstall pisaucer-toolbox
uv tool uninstall pisaucer-toolbox
python3 -m pip uninstall pisaucer-toolbox
```
