import re


def calculate(command):

    numbers = re.findall(r'\d+', command)

    if len(numbers) < 2:
        return None

    numbers = [int(number) for number in numbers]

    if "plus" in command or "+" in command:
        return numbers[0] + numbers[1]

    if "min" in command or "-" in command:
        return numbers[0] - numbers[1]

    if "keer" in command or "*" in command:
        return numbers[0] * numbers[1]

    if "gedeeld" in command or "/" in command:
        return numbers[0] / numbers[1]

    return None