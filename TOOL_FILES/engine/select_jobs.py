#!/usr/bin/env python3
"""
select_jobs.py - Handle job selection and create summary file.

Usage: python select_jobs.py "1,3,5"
       python select_jobs.py "1-3,5"
       python select_jobs.py "2,4-6,8"
"""

import sys
import json
from pathlib import Path
from datetime import datetime

def main():
    if len(sys.argv) < 2:
        print("Usage: python select_jobs.py \"1,3,5\"")
        sys.exit(1)

    job_numbers = sys.argv[1]

    # Import the function from find_jobs_combined
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from engine.find_jobs_combined import create_selected_summary

    try:
        summary_file = create_selected_summary(job_numbers)
        print(f"\n✓ Summary created: {summary_file}")

        # Also create a readable version
        summary_txt = Path(summary_file).parent / "jobs_to_apply.txt"
        print(f"✓ Human-readable: {summary_txt}")

        # Show preview
        with open(summary_txt, 'r', encoding='utf-8') as f:
            content = f.read()
            print("\n" + "=" * 70)
            print(content[:500])  # First 500 chars
            if len(content) > 500:
                print(f"... ({len(content) - 500} more characters)")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
