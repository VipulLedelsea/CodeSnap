package mn.mde.finance.aid;

import java.io.IOException;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.Vector;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

public class AidLookupServlet extends HttpServlet implements AuditSource {
    private static final String DB_URL = "jdbc:db2://mdedb01:50000/AIDPROD";
    private AidCalculator calculator = new AidCalculator();

    public void doGet(HttpServletRequest req, HttpServletResponse resp) throws ServletException, IOException {
        String districtId = req.getParameter("district");
        Vector rows = loadAid(districtId);
        double total = calculator.total(rows);
        AuditLog.record("lookup", districtId);
        resp.getWriter().println(total);
    }

    private Vector loadAid(String districtId) {
        Vector rows = new Vector();
        try {
            Connection conn = DriverManager.getConnection(DB_URL, "aiduser", "Winter2009");
            PreparedStatement ps = conn.prepareStatement(
                "SELECT DISTRICT_ID, TOTAL_AMOUNT FROM MDE.DISTRICT_AID WHERE DISTRICT_ID = ?");
            ps.setString(1, districtId);
            ResultSet rs = ps.executeQuery();
            while (rs.next()) {
                rows.addElement(rs.getString("TOTAL_AMOUNT"));
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
        return rows;
    }

    public String sourceName() {
        return "AidLookupServlet";
    }
}
