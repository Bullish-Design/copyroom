# Pinned native jj 0.46.0. Three callers share this file: the development shell
# (dev/devenv.nix), the consumer module (modules/copyroom.nix), and the flake checks
# (flake.nix). nixpkgs lags: it lacks jj 0.46.0, which adds `workspace add --colocate`, which
# gitman needs. Replace this file with `pkgs.jujutsu` once nixpkgs ships 0.46 or later.
# On a system with no release asset below, this file returns `pkgs.jujutsu`.
{ pkgs }:

let
  version = "0.46.0";
  assets = {
    x86_64-linux = {
      target = "x86_64-unknown-linux-musl";
      hash = "sha256-/OAnEVjmZc64LcZsXrlbFyhkkJTpEzB087W67ONF/Ag=";
    };
    aarch64-linux = {
      target = "aarch64-unknown-linux-musl";
      hash = "sha256-gOKPdQHBHlDgygbNah+h2YLP+cxZv+RBGp02qlAdhn4=";
    };
  };
  asset = assets.${pkgs.stdenv.hostPlatform.system} or null;
in
if asset == null then
  pkgs.jujutsu
else
  pkgs.stdenvNoCC.mkDerivation {
    pname = "jujutsu-bin";
    inherit version;
    src = pkgs.fetchurl {
      url = "https://github.com/jj-vcs/jj/releases/download/v${version}/jj-v${version}-${asset.target}.tar.gz";
      inherit (asset) hash;
    };
    sourceRoot = ".";
    installPhase = ''
      install -Dm755 jj $out/bin/jj
    '';
  }
