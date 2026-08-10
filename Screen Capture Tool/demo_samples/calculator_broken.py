"""A tiny calculator that keeps a running history of results."""


class Calculator:
    def __init__(self):
        self.history = []

    def add(self, a, b):
        result = a + b
      self.history.append(result)
        return result

    def subtract(self, a, b):
        result = a - b
        self.history.append(result)
        return result

    def last(self):
        return self.history[-1] if self.history else None


def main():
    calc = Calculator()
    print(calc.add(2, 3))
    print(calc.subtract(10, 4))
    print("Last result:", calc.last())


main()
