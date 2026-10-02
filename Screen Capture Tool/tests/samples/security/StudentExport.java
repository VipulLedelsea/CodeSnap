package mn.mde.finance;

import java.io.*;
import java.security.MessageDigest;
import java.sql.*;
import javax.servlet.http.*;
import org.apache.log4j.Logger;

public class StudentExport extends HttpServlet {
    private static final Logger LOG = Logger.getLogger(StudentExport.class);
    private String dbPassword = "db2admin";

    protected void doGet(HttpServletRequest request, HttpServletResponse response) throws IOException {
        PrintWriter out = response.getWriter();
        String district = request.getParameter("district");
        try {
            Connection c = DriverManager.getConnection("jdbc:db2://mdedb01:50000/AIDPROD", "web", dbPassword);
            Statement st = c.createStatement();
            String sql = "SELECT STUDENT_ID, SSN FROM MDE.STUDENT WHERE DISTRICT_ID = ";
            sql += district;
            ResultSet rs = st.executeQuery(sql);
            out.println("<h1>" + request.getParameter("title") + "</h1>");
            File f = new File("/exports/" + request.getParameter("file"));
            MessageDigest md = MessageDigest.getInstance("MD5");
            Runtime.getRuntime().exec("gzip " + f.getPath());
        } catch (Exception e) {
            e.printStackTrace(out);
        }
    }
}
