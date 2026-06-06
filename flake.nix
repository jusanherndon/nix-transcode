{
  description = "A Python Package";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        lib = pkgs.lib;

        python = pkgs.python313;
        pythonPackages = pkgs.python313Packages;

        pyproject = builtins.fromTOML (builtins.readFile ./pyproject.toml);
        project = pyproject.project;

        ffmpegRuntime = pkgs.ffmpeg-full;

        package = pythonPackages.buildPythonPackage {
          pname = project.name;
          inherit (project) version;

          pyproject = true;
          src = ./.;

          build-system = [
            pythonPackages.hatchling
          ];

          nativeBuildInputs = [
            pkgs.makeWrapper
          ];

          propagatedBuildInputs = [
            pythonPackages.click
            pythonPackages."python-ffmpeg"
          ];

          nativeCheckInputs = [
            pythonPackages.pytest
            pythonPackages.ruff
          ];

          checkPhase = ''
            runHook preCheck
            pytest -q
            ruff check .
            runHook postCheck
          '';

          postInstall = ''
            wrapProgram $out/bin/transcode \
              --prefix PATH : ${lib.makeBinPath [ ffmpegRuntime ]}
          '';
        };

        editablePackage = python.pkgs.mkPythonEditablePackage {
          pname = project.name;
          inherit (project) scripts version;
          root = "$PWD";
        };
      in
      {
        packages = {
          "${project.name}" = package;
          default = self.packages.${system}.${project.name};
        };

        apps = {
          "${project.name}" = flake-utils.lib.mkApp {
            drv = package;
            exePath = "/bin/transcode";
          };
          default = self.apps.${system}.${project.name};
        };

        devShells = {
          default = pkgs.mkShell {
            inputsFrom = [ package ];

            buildInputs = [
              editablePackage

              ffmpegRuntime

              pythonPackages.build
              pythonPackages.hatchling
              pythonPackages.ipython
              pythonPackages.pytest
              pythonPackages.ruff
              pythonPackages."python-ffmpeg"
              pythonPackages.click

              pythonPackages.python-lsp-server
              pythonPackages.python-lsp-ruff
            ];
          };
        };
      });
}
