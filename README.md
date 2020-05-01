# LSP-lemminx

XML support for Sublime Text's LSP plugin.

Uses [XML Language Server (LemMinX)](https://github.com/eclipse/lemminx) to provide completions, validation, formatting and other features for XML files. See linked repository for more information.

1. Install [LSP](https://packagecontrol.io/packages/LSP) and `LSP-lemminx` from Package Control.
2. Wait for the language server binary download to complete.
3. Restart Sublime Text.


### Notes:

1. LemMinX requires the Java Runtime (JRE) to be installed. To check that, run `java -version` in your login shell.
2. The plugin does not distribute, but download the `org.eclipse.lemminx-${version}-uber.jar` binary from the official source.


### Configuration

Open configuration file using command palette with `Preferences: LSP-lemminx Settings` command or opening it from the Sublime menu (`Preferences > Package Settings > LSP > Servers > LSP-lemminx`).
