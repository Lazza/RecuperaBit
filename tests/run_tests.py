"""Test runner and configuration for RecuperaBit test suite."""

import unittest
import sys
import os
import logging
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import test modules
from tests.test_ntfs_unit import *
from tests.test_ntfs_e2e import *
from tests.test_integration import *


def create_test_suite():
    """Create and return the complete test suite."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add unit tests
    suite.addTests(loader.loadTestsFromModule(sys.modules['tests.test_ntfs_unit']))
    
    # Add integration tests
    suite.addTests(loader.loadTestsFromModule(sys.modules['tests.test_integration']))
    
    # Add E2E tests (these may be skipped if tools are not available)
    suite.addTests(loader.loadTestsFromModule(sys.modules['tests.test_ntfs_e2e']))
    
    return suite


def run_unit_tests_only():
    """Run only unit tests (fast, no external dependencies)."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromModule(sys.modules['tests.test_ntfs_unit']))
    suite.addTests(loader.loadTestsFromModule(sys.modules['tests.test_integration']))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


def run_e2e_tests_only():
    """Run only end-to-end tests (slower, requires system tools)."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromModule(sys.modules['tests.test_ntfs_e2e']))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


def run_all_tests():
    """Run the complete test suite."""
    suite = create_test_suite()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


def main():
    """Main test runner with command line options."""
    import argparse
    
    parser = argparse.ArgumentParser(description='RecuperaBit Test Runner')
    parser.add_argument('--unit', action='store_true', 
                       help='Run only unit tests (fast)')
    parser.add_argument('--e2e', action='store_true',
                       help='Run only end-to-end tests (requires system tools)')
    parser.add_argument('--integration', action='store_true',
                       help='Run only integration tests')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose logging output')
    parser.add_argument('--debug', action='store_true',
                       help='Debug level logging')
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.WARNING
    if args.verbose:
        log_level = logging.INFO
    if args.debug:
        log_level = logging.DEBUG
        
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run selected tests
    success = True
    
    if args.unit:
        print("Running unit tests only...")
        success = run_unit_tests_only()
    elif args.e2e:
        print("Running end-to-end tests only...")
        success = run_e2e_tests_only()
    elif args.integration:
        print("Running integration tests only...")
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        suite.addTests(loader.loadTestsFromModule(sys.modules['tests.test_integration']))
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        success = result.wasSuccessful()
    else:
        print("Running complete test suite...")
        success = run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
