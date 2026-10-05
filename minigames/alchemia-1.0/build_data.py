"""Compatibility entry point: data.json is canonical and is never overwritten."""
from verify_content import validate
if __name__ == '__main__':
    report = validate(check_art=False)
    print('Validated canonical data.json:', report['elements'], 'elements')
