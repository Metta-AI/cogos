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

        packagesList = with pkgs; [
          graphite-cli
          moreutils # ts for timestamped logs in Tilt
          nodejs_20
          sqlite # For inspecting the db
          tilt
          uv
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = packagesList;
          shellHook = ''
            export PATH="$PWD/.venv/bin:$PATH"
          '';
        };
      }
    );
}
