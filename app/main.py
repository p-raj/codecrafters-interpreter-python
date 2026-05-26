from enum import StrEnum
import sys
from .lox import Lox


class Command(StrEnum):
    TOKENIZE = "tokenize"
    PARSE = "parse"


def main():
    if len(sys.argv) < 3:
        print("Usage: ./your_program.sh tokenize <filename>", file=sys.stderr)
        exit(1)

    command = Command(sys.argv[1])
    filename = sys.argv[2]

    if command not in {Command.TOKENIZE, Command.PARSE}:
        print(f"Unknown command: {command}", file=sys.stderr)
        exit(1)

    with open(filename) as file:
        file_contents = file.read()

    # You can use print statements as follows for debugging, they'll be visible when running tests.
    print("Logs from your program will appear here!", file=sys.stderr)

    # TODO: Uncomment the code below to pass the first stage

    if file_contents:
        Lox(command).run(file_contents)
    else:
        print(
            "EOF  null"
        )  # Placeholder, replace this line when implementing the scanner


if __name__ == "__main__":
    main()
