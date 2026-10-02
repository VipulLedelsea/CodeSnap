**FREE
ctl-opt dftactgrp(*no);
dcl-f LEVYCERT usage(*update) keyed;
dcl-f LEVYDSPF workstn;
dcl-s total packed(11:2);

dcl-proc main;
  setll *loval LEVYCERT;
  read LEVYCERT;
  dow not %eof(LEVYCERT);
    checkLevy();
    read LEVYCERT;
  enddo;
  exfmt LEVYSCR;
  callp LEVYRPT(total);
end-proc;

dcl-proc checkLevy;
  total += AMOUNT;
  update LEVYCERT;
end-proc;
