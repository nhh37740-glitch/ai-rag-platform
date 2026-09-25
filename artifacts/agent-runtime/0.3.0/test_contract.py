import importlib
import unittest

class Contract(unittest.TestCase):
    def test_import(self):
        m = importlib.import_module('agent_runtime')
        self.assertTrue(hasattr(m, '__version__'))

if __name__ == '__main__':
    unittest.main()
