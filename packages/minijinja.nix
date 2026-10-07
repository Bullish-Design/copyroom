{ lib, fetchurl, buildPythonPackage, stdenv }:

let
  wheels = {
    "x86_64-linux" = {
      url = "https://files.pythonhosted.org/packages/ad/ed/14056592c0008a0945e96966c5e2b215579d6f3487032d7ba2d8ad2e9c12/minijinja-2.24.0-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl";
      hash = "sha256-taTb1z8sAqttCrC2K2in0lV+XUVyPTtOQjt8OHfzHK0=";
    };
    "aarch64-linux" = {
      url = "https://files.pythonhosted.org/packages/82/ec/9a1e7513d7e18ff11907eb6ae92f060f2abd85e0df029625816b8f469eb4/minijinja-2.24.0-cp38-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl";
      hash = "sha256-qeJS+kxZz/F5Tf/7U0naakiF3peqry+8aYO+zB65c+k=";
    };
    "x86_64-darwin" = {
      url = "https://files.pythonhosted.org/packages/a0/16/9170db3a85bf7fed14c5281e13927d310385e5fd945518dda80e2ec0a631/minijinja-2.24.0-cp38-abi3-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl";
      hash = "sha256-8oYQb50v/XNwKkcMxNkmKxWI60iRb8hLmNGd9OMGS9Q=";
    };
    "aarch64-darwin" = {
      url = "https://files.pythonhosted.org/packages/a0/16/9170db3a85bf7fed14c5281e13927d310385e5fd945518dda80e2ec0a631/minijinja-2.24.0-cp38-abi3-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl";
      hash = "sha256-8oYQb50v/XNwKkcMxNkmKxWI60iRb8hLmNGd9OMGS9Q=";
    };
  };
  wheel = wheels.${stdenv.hostPlatform.system} or (throw "MiniJinja has no wheel for ${stdenv.hostPlatform.system}");
in
buildPythonPackage {
  pname = "minijinja";
  version = "2.24.0";
  format = "wheel";

  src = fetchurl {
    inherit (wheel) url hash;
  };

  doCheck = false;
  pythonImportsCheck = [ "minijinja" ];

  meta = with lib; {
    description = "MiniJinja Python bindings";
    license = licenses.asl20;
    platforms = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
  };
}
