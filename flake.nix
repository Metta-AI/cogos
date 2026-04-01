{
  description = "Health data analysis environment";

  inputs = {
    nixpkgs.url = "nixpkgs/nixos-unstable";
    utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      utils,
    }:
    utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        # Wraps chromium with fonts and dbus so it works in containers without system fonts. Without this, chrome logs a
        # lot of errors and hits some fatal errors
        fontsConf = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
        dbusConf = pkgs.writeText "dbus-dummy-system.conf" ''
          <!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
            "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
          <busconfig>
            <type>custom</type>
            <listen>unix:tmpdir=/tmp</listen>
            <auth>EXTERNAL</auth>
            <policy context="default">
              <allow send_destination="*" eavesdrop="true"/>
              <allow eavesdrop="true"/>
              <allow own="*"/>
            </policy>
          </busconfig>
        '';
        chromium-headless = pkgs.writeShellScriptBin "chromium" ''
          export FONTCONFIG_FILE="${fontsConf}"
          # Start a dummy system bus if none exists
          if [ ! -S /run/dbus/system_bus_socket ]; then
            DBUS_SYSTEM_SOCKET=$(${pkgs.dbus}/bin/dbus-daemon --config-file="${dbusConf}" --print-address --fork 2>/dev/null)
            export DBUS_SYSTEM_BUS_ADDRESS="$DBUS_SYSTEM_SOCKET"
          fi
          exec "${pkgs.dbus}/bin/dbus-run-session" \
            --dbus-daemon="${pkgs.dbus}/bin/dbus-daemon" \
            --config-file="${pkgs.dbus}/share/dbus-1/session.conf" \
            "${pkgs.chromium}/bin/chromium" "$@"
        '';

        agent-browser = pkgs.stdenv.mkDerivation rec {
          pname = "agent-browser";
          version = "0.23.4";

          src = pkgs.fetchurl {
            url = "https://registry.npmjs.org/agent-browser/-/agent-browser-${version}.tgz";
            hash = "sha256-uLi7Ksem211kEFQaa00yIDbGM8IN8GyY/HzE6vtji18=";
          };

          nativeBuildInputs = [ pkgs.autoPatchelfHook ];
          buildInputs = [ pkgs.stdenv.cc.cc.lib ];

          unpackPhase = ''
            tar xzf $src
          '';

          installPhase = ''
            mkdir -p $out/bin
            cp package/bin/agent-browser-linux-x64 $out/bin/agent-browser
            chmod +x $out/bin/agent-browser
          '';
        };

        packagesList = with pkgs; [
          graphite-cli
          moreutils # ts for timestamped logs in Tilt
          nodejs_20
          sqlite # For inspecting the db
          tilt
          uv
          agent-browser
          chromium-headless
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = packagesList;
          shellHook = ''
            export PATH="$PWD/.venv/bin:$PATH"
            export AGENT_BROWSER_EXECUTABLE_PATH="${chromium-headless}/bin/chromium"
          '';
        };
      }
    );
}
