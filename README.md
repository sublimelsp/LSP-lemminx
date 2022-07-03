# LSP-lemminx

XML support for Sublime Text's LSP plugin.

Uses [XML Language Server (LemMinX)](https://github.com/eclipse/lemminx)
to provide completions, validation, formatting and other features for XML files.
See linked repository for more information.

## Installation

1. Install [LSP](https://packagecontrol.io/packages/LSP) and [LSP-lemminx](https://packagecontrol.io/Packages/LSP-lemminx) from Package Control.
2. Restart Sublime Text.

> **Note**
>
> The plugin ...
> 1. does not distribute but download language server binaries from official sources.
> 2. prefers GraalVM compiled binaries by default to avoid Java Runtime dependencies.

### Configuration

Open configuration file 
by running `Preferences: LSP-lemminx Settings` from Command Palette 
or via Main Menu (`Preferences > Package Settings > LSP > Servers > LSP-lemminx`).
