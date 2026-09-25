import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import control_plane as cp

class RepositorySelfValidationTests(unittest.TestCase):
    def test_repository_task_registry_and_lease_projection_is_valid(self):
        self.assertEqual(cp.validate_repository(ROOT),[])

if __name__=="__main__":
    unittest.main()
