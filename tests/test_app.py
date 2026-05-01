import importlib.util
import pathlib
import unittest


APP_PATH = pathlib.Path(__file__).resolve().parents[1] / "app.py"


def load_app_module():
    spec = importlib.util.spec_from_file_location("idp_testing_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RouteRegistrationTest(unittest.TestCase):
    def test_runtime_health_routes_are_registered(self):
        module = load_app_module()
        routes = {rule.rule for rule in module.app.url_map.iter_rules()}

        self.assertIn("/healthz", routes)
        self.assertIn("/ping", routes)
        self.assertIn("/api/version", routes)


if __name__ == "__main__":
    unittest.main()
