import re


def calculate(command):

    numbers = re.findall(r'\d+(?:\.\d+)?', command)

    if len(numbers) < 2:
        return None

    numbers = [float(number) for number in numbers]

    def show(number):
        return int(number) if number.is_integer() else number

    if "plus" in command or "+" in command:
        result = numbers[0] + numbers[1]
        operation = f"{show(numbers[0])} + {show(numbers[1])}"

    elif "min" in command or "-" in command:
        result = numbers[0] - numbers[1]
        operation = f"{show(numbers[0])} - {show(numbers[1])}"

    elif "keer" in command or "*" in command:
        result = numbers[0] * numbers[1]
        operation = f"{show(numbers[0])} × {show(numbers[1])}"

    elif "gedeeld" in command or "/" in command:
        if numbers[1] == 0:
            return {
                "operation": f"{show(numbers[0])} ÷ 0",
                "result": "Delen door nul is niet mogelijk.",
            }
        result = numbers[0] / numbers[1]
        operation = f"{show(numbers[0])} ÷ {show(numbers[1])}"

    else:
        return None

    # Hele getallen netjes weergeven
    if result.is_integer():
        result = int(result)

    return {
        "operation": operation,
        "result": result
    }