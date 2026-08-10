from dataclasses import dataclass


@dataclass
class Book:
    title: str
    author: str
    available: bool = True


class Library:
    def __init__(self, name):
        self.name = name
        self.books = []

    def add(self, book):
        self.books.append(book)

    def checkout(self, title):
        for book in self.books:
            if book.title == title and book.available:
                book.available = False
                return True
        return False

    def available(self):
        return sum(1 for b in self.books if b.available)


def main():
    lib = Library("Ledelsea Library")
    lib.add(Book("Clean Code", "Martin"))
    lib.add(Book("Refactoring", "Fowler"))
    lib.checkout("Clean Code")
    print(f"{lib.available()} of {len(lib.books)} available")


main()
