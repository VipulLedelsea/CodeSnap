using System;
using MicroFocus.COBOL.Program;

namespace MDE.Legacy.AidCalc
{
    public class AIDCALC
    {
        private decimal WS_TOTAL_AMOUNT;
        private int WS_STUDENT_COUNT;
        private string WS_EOF_FLAG = "N";

        public void P0000_MAIN_PARA()
        {
            P1000_READ_DISTRICT_PARA();
            while (WS_EOF_FLAG != "Y")
            {
                P2000_CALC_AID_PARA();
            }
            goto P9999_EXIT;
        P9999_EXIT:
            return;
        }

        private void P1000_READ_DISTRICT_PARA()
        {
            WS_EOF_FLAG = DistrictFile.ReadNext() ? "N" : "Y";
        }

        private void P2000_CALC_AID_PARA()
        {
            WS_TOTAL_AMOUNT = WS_STUDENT_COUNT * 7138.00m;
            P1000_READ_DISTRICT_PARA();
        }
    }
}
