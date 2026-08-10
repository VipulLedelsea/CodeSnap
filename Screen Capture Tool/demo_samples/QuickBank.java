public class QuickBank {

    static class Account {
        private double balance;

        Account(double opening) {
            this.balance = opening;
        }

        void deposit(double amount) {
            if (amount > 0) balance += amount;
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
    }

    public static void main(String[] args) {
        Account acc = new Account(500.0);
        acc.deposit(150.0);
        acc.withdraw(100.0);
        System.out.println("Balance: " + acc.getBalance());
    }
}
