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

        ffmpegQualityMetrics = pythonPackages.buildPythonPackage rec {
          pname = "ffmpeg-quality-metrics";
          version = "3.12.0";
          pyproject = true;

          src = pythonPackages.fetchPypi {
            pname = "ffmpeg_quality_metrics";
            inherit version;
            hash = "sha256-m6Yte7EzL18cychFjFxA8Zcsae4eh3FMIkX4yNvZiFE=";
          };

          build-system = [
            pythonPackages.uv-build
          ];

          dependencies = [
            pythonPackages.ffmpeg-progress-yield
            pythonPackages.tqdm
          ];

          postPatch = ''
            sed -i 's/requires = \["uv_build[^"]*"]/requires = ["uv_build"]/' pyproject.toml
            sed -i '/license-files = \["LICENSE.md"]/d' pyproject.toml
          '';

          doCheck = false;

          pythonImportsCheck = [ "ffmpeg_quality_metrics" ];

          meta = {
            description = "Calculate video quality metrics with FFmpeg (SSIM, PSNR, VMAF)";
            homepage = "https://github.com/slhck/ffmpeg-quality-metrics";
            license = lib.licenses.mit;
            mainProgram = "ffmpeg-quality-metrics";
          };
        };

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
            ffmpegQualityMetrics
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
              ffmpegQualityMetrics

              pythonPackages.python-lsp-server
              pythonPackages.python-lsp-ruff
            ];
          };
        };
      });
}
