{
  description = "CopyRoom: a mode-aware CLI for local Templateer and jj project workflows.";

  # The devenv module stays in `modules/copyroom.nix` and `devenv.nix`. This flake adds the
  # `copyroom` command as a plain package, with the pinned `pyjutsu` guard.
  #
  # Outputs:
  #   packages.default / packages.copyroom   the `copyroom` command
  #   overlays.default                       adds `pyjutsu`, `minijinja`, `templateer`, and
  #                                          `copyroom` to pythonPackagesExtensions
  #   checks.copyroom                        the package build; it runs the suite
  #
  # CopyRoom runs `jj` from the host PATH. Install one `jj` on the host. The package does not
  # wrap a second one.
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/e7439b6b14ad3cc35d05608ebca9bce01a25f5f8";

    pyjutsu = {
      url = "git+https://github.com/Bullish-Design/Pyjutsu?ref=refs/tags/v0.23.1";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    templateer = {
      url = "git+https://github.com/Bullish-Design/templateer_v2?ref=refs/tags/v0.4.2";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, pyjutsu, templateer }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;

      copyroomOverlay = final: prev: {
        pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
          (pyFinal: _pyPrev: {
            copyroom = pyFinal.callPackage ./packages/copyroom-cli.nix {
              pyjutsu = pyFinal.pyjutsu;
              runTests = true;
              inherit (final) jujutsu git patch;
            };
          })
        ];
      };

      overlay = nixpkgs.lib.composeManyExtensions [
        pyjutsu.overlays.default
        templateer.overlays.default
        copyroomOverlay
      ];

      pkgsFor = system: import nixpkgs { inherit system; overlays = [ overlay ]; };
    in
    {
      overlays.default = overlay;

      packages = forAllSystems (system:
        let
          python = (pkgsFor system).python313Packages;
        in
        {
          copyroom = python.toPythonApplication python.copyroom;
          default = python.toPythonApplication python.copyroom;
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.copyroom}/bin/copyroom";
        };
      });

      checks = forAllSystems (system: {
        copyroom = self.packages.${system}.copyroom;
      });
    };
}
