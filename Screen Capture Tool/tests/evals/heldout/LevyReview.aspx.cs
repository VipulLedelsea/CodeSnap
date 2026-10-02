using System;
using System.Data.SqlClient;
using System.Web.UI;

namespace MDE.Levy.Web
{
    public partial class LevyReview : Page
    {
        protected void Page_Load(object sender, EventArgs e)
        {
            if (!IsPostBack) BindGrid();
        }

        private void BindGrid()
        {
            using (var cn = new SqlConnection("Data Source=MDESQL03;Initial Catalog=Levy;Integrated Security=SSPI"))
            {
                var cmd = new SqlCommand("SELECT DistrictId, Amount FROM dbo.LevyCert", cn);
                grid.DataSource = cmd.ExecuteReader();
            }
        }

        protected void btnApprove_Click(object sender, EventArgs e)
        {
            new LevyService().Approve(txtDistrict.Text);
            Response.Redirect("LevyDone.aspx");
        }
    }
}
