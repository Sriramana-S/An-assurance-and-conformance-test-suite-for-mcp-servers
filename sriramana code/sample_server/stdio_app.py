import json
import sys
from json import JSONDecodeError

from sample_server.app import handle_message, parse_error


def write_message(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except JSONDecodeError:
            write_message(parse_error())
            continue

        if isinstance(data, list):
            responses = [
                response for response in (handle_message(item) for item in data)
                if response is not None
            ]
            if responses:
                write_message(responses)
            continue

        response = handle_message(data)
        if response is not None:
            write_message(response)


if __name__ == "__main__":
    main()
