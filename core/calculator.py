import re


def calculate(command):

    numbers = re.findall(r'\d+(?:\.\d+)?', command)

    if len(numbers) < 2:
        return None

    numbers = [float(number) for number in numbers]

    if "plus" in command or "+" in command:
        result = numbers[0] + numbers[1]
        operation = f"{numbers[0]} + {numbers[1]}"

    elif "min" in command or "-" in command:
        result = numbers[0] - numbers[1]
        operation = f"{numbers[0]} - {numbers[1]}"

    elif "keer" in command or "*" in command:
        result = numbers[0] * numbers[1]
        operation = f"{numbers[0]} × {numbers[1]}"

    elif "gedeeld" in command or "/" in command:
        result = numbers[0] / numbers[1]
        operation = f"{numbers[0]} ÷ {numbers[1]}"

    else:
        return None

    # Hele getallen netjes weergeven
    if result.is_integer():
        result = int(result)

    return {
        "operation": operation,
        "result": result
    }