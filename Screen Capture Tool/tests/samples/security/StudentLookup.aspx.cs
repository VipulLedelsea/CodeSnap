using System;
using System.Data.SqlClient;
using System.Runtime.Serialization.Formatters.Binary;
using System.Security.Cryptography;

namespace MDE.Finance.Web
{
    public partial class StudentLookup : System.Web.UI.Page
    {
        private const string AdminPassword = "Summer2009!";

        protected void btnFind_Click(object sender, EventArgs e)
        {
            string marss = Request.QueryString["marss"];
            string sql = "SELECT MARSS_NBR, BIRTH_DATE FROM STUDENT WHERE MARSS_NBR = '" + marss + "'";
            var cmd = new SqlCommand(sql, new SqlConnection("Server=MDESQL02;Database=Students;Encrypt=False;Integrated Security=true"));
            lblName.Text = Request.QueryString["name"];
            try { cmd.ExecuteReader(); }
            catch (Exception ex) { Response.Write(ex.Message); }
        }

        private string Hash(string value)
        {
            var md5 = new MD5CryptoServiceProvider();
            return Convert.ToBase64String(md5.ComputeHash(System.Text.Encoding.UTF8.GetBytes(value)));
        }

        private object Load(System.IO.Stream s)
        {
            // BinaryFormatter is only mentioned in this comment
            return new BinaryFormatter().Deserialize(s);
        }

        private string Safe(string id)
        {
            string q = "SELECT * FROM DISTRICT WHERE ID = @id AND TYPE = " + TYPE_CODE;
            return q;
        }

        private const string TYPE_CODE = "'01'";
    }
}
