from euronext_pde.paths import ProjectPaths


def test_project_paths_exist() -> None:
    paths = ProjectPaths.discover()

    assert paths.root.exists()
    assert paths.config.exists()
    assert paths.data.exists()
    assert paths.outputs.exists()
