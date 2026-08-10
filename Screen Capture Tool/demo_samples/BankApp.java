// A small banking model — demo sample for Code Capture.
import java.util.ArrayList;
import java.util.List;

class Account {
    private final String owner;
    private double balance;

    Account(String owner, double opening) {
        this.owner = owner;
        this.balance = opening;
    }

    void deposit(double amount) {
        if (amount > 0) {
            balance += amount;
        }
    }

    boolean withdraw(double amount) {
        if (amount > 0 && amount <= balance) {
            balance -= amount;
            return true;
        }
        return false;
    }

    double getBalance() {
        return balance;
    }

    String getOwner() {
        return owner;
    }
}

class Bank {
    private final String name;
    private final List<Account> accounts = new ArrayList<>();

    Bank(String name) {
        this.name = name;
    }

    Account open(String owner, double opening) {
        Account account = new Account(owner, opening);
        accounts.add(account);
        return account;
    }

    Account findByOwner(String owner) {
        for (Account account : accounts) {
            if (account.getOwner().equals(owner)) {
                return account;
            }
        }
        return null;
    }

    double totalDeposits() {
        double total = 0;
        for (Account account : accounts) {
            total += account.getBalance();
        }
        return total;
    }

    int size() {
        return accounts.size();
    }
}

public class BankApp {
    public static void main(String[] args) {
        Bank bank = new Bank("Ledelsea Bank");
        Account alice = bank.open("Alice", 500.0);
        Account bob = bank.open("Bob", 250.0);

        alice.deposit(150.0);
        if (bob.withdraw(100.0)) {
            System.out.println("Bob withdrew 100");
        }

        Account found = bank.findByOwner("Alice");
        if (found != null) {
            System.out.println(found.getOwner() + " balance: " + found.getBalance());
        }

        System.out.println("Accounts: " + bank.size());
        System.out.println("Total deposits: " + bank.totalDeposits());
    }
}
