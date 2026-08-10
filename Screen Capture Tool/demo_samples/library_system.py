"""A small in-memory library catalog — demo sample for Code Capture."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Book:
    title: str
    author: str
    isbn: str
    available: bool = True


class Member:
    def __init__(self, name: str):
        self.name = name
        self.borrowed: List[str] = []

    def borrow(self, isbn: str) -> None:
        self.borrowed.append(isbn)

    def give_back(self, isbn: str) -> None:
        if isbn in self.borrowed:
            self.borrowed.remove(isbn)


class Library:
    """Holds the catalog and lends books to members."""

    def __init__(self, name: str):
        self.name = name
        self.books: List[Book] = []
        self.members: List[Member] = []

    def add_book(self, book: Book) -> None:
        self.books.append(book)

    def register(self, member: Member) -> None:
        self.members.append(member)

    def find_by_isbn(self, isbn: str) -> Optional[Book]:
        for book in self.books:
            if book.isbn == isbn:
                return book
        return None

    def find_by_author(self, author: str) -> List[Book]:
        return [b for b in self.books if b.author == author]

    def checkout(self, member: Member, isbn: str) -> bool:
        book = self.find_by_isbn(isbn)
        if book is not None and book.available:
            book.available = False
            member.borrow(isbn)
            return True
        return False

    def return_book(self, member: Member, isbn: str) -> bool:
        book = self.find_by_isbn(isbn)
        if book is not None and not book.available:
            book.available = True
            member.give_back(isbn)
            return True
        return False

    def available_count(self) -> int:
        return sum(1 for b in self.books if b.available)


def main() -> None:
    library = Library("Ledelsea Library")
    library.add_book(Book("The Pragmatic Programmer", "Hunt", "978-0135957059"))
    library.add_book(Book("Clean Code", "Martin", "978-0132350884"))
    library.add_book(Book("Refactoring", "Fowler", "978-0201485677"))

    alice = Member("Alice")
    library.register(alice)

    count = library.available_count()
    print(f"{library.name} has {count} books available")

    if library.checkout(alice, "978-0132350884"):
        print(f"{alice.name} checked out 'Clean Code'")

    for book in library.find_by_author("Martin"):
        status = "available" if book.available else "on loan"
        print(f"  {book.title} by {book.author} — {status}")

    print(f"Now {library.available_count()} books available")


if __name__ == "__main__":
    main()
