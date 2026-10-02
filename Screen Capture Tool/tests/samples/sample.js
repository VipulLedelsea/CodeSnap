function fib(n) {
  let a = 0, b = 1;
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push(a);
    [a, b] = [b, a + b];
  }
  return out;
}

console.log(fib(10));
