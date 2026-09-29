using System;
using System.Collections;
using System.Data.SqlClient;
using System.Web.Mvc;

namespace MDE.Finance.Web
{
    [RoutePrefix("aid")]
    public class AidPaymentController : Controller, IAuditable
    {
        private readonly PaymentService _service = new PaymentService();
        private const string ConnStr = "Data Source=MDESQL02;Initial Catalog=SchoolFinance;User ID=web;Password=P@ssw0rd1";

        [HttpGet]
        [Route("district/{id}")]
        public ActionResult District(string id)
        {
            var total = _service.TotalFor(id);
            ArrayList history = LoadHistory(id);
            return View(total);
        }

        [HttpPost]
        public ActionResult Approve(string id)
        {
            using (var conn = new SqlConnection(ConnStr))
            {
                var cmd = new SqlCommand("UPDATE dbo.PaymentBatch SET Status = 'A' WHERE DistrictId = @id", conn);
                cmd.ExecuteNonQuery();
            }
            AuditTrail.Write("approve", id);
            return RedirectToAction("District", new { id = id });
        }

        private ArrayList LoadHistory(string id)
        {
            var list = new ArrayList();
            string sql = "SELECT PaidOn, Amount FROM dbo.PaymentHistory h " +
                         "JOIN dbo.District d ON d.Id = h.DistrictId WHERE d.Id = @id";
            return list;
        }
    }
}
