// Included inside occ_agent.cpp's anonymous namespace; all geometry is OCCT 7.7.
double real(const J& j, const char* key, double fallback) {
  if (!j.HasMember(key)) return fallback;
  if (!j[key].IsNumber() || !std::isfinite(j[key].GetDouble())) throw std::runtime_error(std::string("Expected finite number: ") + key);
  return j[key].GetDouble();
}
J direction(const gp_Dir& d, A& a) { return point(gp_Pnt(d.X(), d.Y(), d.Z()), a); }
J integers(const std::set<int>& values, A& a) {
  J out(rapidjson::kArrayType); for (int v : values) out.PushBack(v, a); return out;
}
std::set<int> faceIndices(const J& request, int total) {
  if (!request.HasMember("faces") || !request["faces"].IsArray() || request["faces"].Empty() || request["faces"].Size() > 500)
    throw std::runtime_error("faces must contain 1-500 distinct 1-based indices");
  std::set<int> result;
  for (const auto& v : request["faces"].GetArray()) {
    if (!v.IsInt() || v.GetInt() < 1 || v.GetInt() > total || !result.insert(v.GetInt()).second)
      throw std::runtime_error("Invalid, duplicate or out-of-range face index");
  }
  return result;
}
void checkRevision(const J& request, const char* key, const TopoDS_Shape& s) {
  if (field(request, key) != revision(s)) throw std::runtime_error("Stale shape revision; inspect and select again");
}
double area(const TopoDS_Shape& s) {
  GProp_GProps p; BRepGProp::SurfaceProperties(s, p, false, false); return p.Mass();
}
double length(const TopoDS_Shape& s) {
  GProp_GProps p; BRepGProp::LinearProperties(s, p, true, false); return p.Mass();
}
double maxTolerance(const TopoDS_Shape& s) {
  double result = 0;
  for (auto type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
    TopTools_IndexedMapOfShape m; TopExp::MapShapes(s, type, m);
    for (int i = 1; i <= m.Extent(); ++i) {
      double t = type == TopAbs_FACE ? BRep_Tool::Tolerance(TopoDS::Face(m(i))) :
                 type == TopAbs_EDGE ? BRep_Tool::Tolerance(TopoDS::Edge(m(i))) : BRep_Tool::Tolerance(TopoDS::Vertex(m(i)));
      result = std::max(result, t);
    }
  }
  return result;
}
const char* surfaceNames[] = {"plane", "cylinder", "cone", "sphere", "torus", "bezier", "bspline", "revolution", "extrusion", "offset", "other"};
struct Support {
  GeomAbs_SurfaceType type;
  gp_Ax1 axis;
  double radius = 0, angle = 0;
};
Support support(const TopoDS_Face& face) {
  BRepAdaptor_Surface s(face);
  Support p; p.type = s.GetType();
  switch (p.type) {
    case GeomAbs_Plane: p.axis = s.Plane().Axis(); break;
    case GeomAbs_Cylinder: p.axis = s.Cylinder().Axis(); p.radius = s.Cylinder().Radius(); break;
    case GeomAbs_Cone: p.axis = s.Cone().Axis(); p.radius = s.Cone().RefRadius(); p.angle = s.Cone().SemiAngle(); break;
    case GeomAbs_Sphere: p.axis = s.Sphere().Position().Axis(); p.radius = s.Sphere().Radius(); break;
    case GeomAbs_Torus: p.axis = s.Torus().Axis(); p.radius = s.Torus().MajorRadius(); break;
    default: break;
  }
  return p;
}
bool coaxial(const gp_Ax1& a, const gp_Ax1& b, double tol = 1e-6) {
  return a.Direction().IsParallel(b.Direction(), 1e-7) && gp_Lin(a).Distance(b.Location()) <= tol;
}
bool sameSupport(const TopoDS_Face& a, const TopoDS_Face& b, double tol) {
  auto p = support(a), q = support(b);
  if (p.type != q.type) return false;
  switch (p.type) {
    case GeomAbs_Plane:
      return p.axis.Direction().IsParallel(q.axis.Direction(), 1e-7) &&
        std::abs(gp_Vec(p.axis.Location(), q.axis.Location()).Dot(gp_Vec(p.axis.Direction()))) <= tol;
    case GeomAbs_Cylinder: return coaxial(p.axis, q.axis, tol) && std::abs(p.radius - q.radius) <= tol;
    case GeomAbs_Cone: {
      if (!coaxial(p.axis, q.axis, tol)) return false;
      double sign = p.axis.Direction().Dot(q.axis.Direction());
      double atP = q.radius + gp_Vec(q.axis.Location(), p.axis.Location()).Dot(gp_Vec(q.axis.Direction())) * std::tan(q.angle);
      return std::abs(std::tan(p.angle) - sign * std::tan(q.angle)) < 1e-7 && std::abs(p.radius - atP) <= tol;
    }
    case GeomAbs_Sphere: return p.axis.Location().Distance(q.axis.Location()) <= tol && std::abs(p.radius-q.radius) <= tol;
    case GeomAbs_Torus: {
      BRepAdaptor_Surface sa(a), sb(b);
      return p.axis.Location().Distance(q.axis.Location()) <= tol && p.axis.Direction().IsParallel(q.axis.Direction(), 1e-7) &&
        std::abs(p.radius-q.radius) <= tol && std::abs(sa.Torus().MinorRadius()-sb.Torus().MinorRadius()) <= tol;
    }
    default: {
      // Conservative fallback: identical world-coordinate support serialization.
      // Reparameterized general surfaces remain unclassified, never silently accepted.
      TopLoc_Location la, lb;
      auto ga = BRep_Tool::Surface(a, la), gb = BRep_Tool::Surface(b, lb);
      if (ga == gb && la == lb) return true;
      std::ostringstream oa, ob;
      GeomTools::Write(Handle(Geom_Surface)::DownCast(ga->Transformed(la.Transformation())), oa);
      GeomTools::Write(Handle(Geom_Surface)::DownCast(gb->Transformed(lb.Transformation())), ob);
      return oa.str() == ob.str();
    }
  }
}
bool inwardWall(const TopoDS_Face& face) {
  BRepAdaptor_Surface s(face);
  if (s.GetType() != GeomAbs_Cylinder && s.GetType() != GeomAbs_Cone) return false;
  double u = (s.FirstUParameter()+s.LastUParameter())*.5, v = (s.FirstVParameter()+s.LastVParameter())*.5;
  gp_Pnt p; gp_Vec du, dv; s.D1(u, v, p, du, dv);
  auto n = du.Crossed(dv); if (face.Orientation() == TopAbs_REVERSED) n.Reverse();
  const auto ax = support(face).axis;
  gp_Vec radial(ax.Location(), p);
  radial -= gp_Vec(ax.Direction()) * radial.Dot(gp_Vec(ax.Direction()));
  return n.Dot(radial) < -1e-12;
}
J faceInfo(const TopoDS_Face& face, int index, const TopTools_IndexedMapOfShape& edgeMap, A& a) {
  BRepAdaptor_Surface s(face);
  auto p = support(face);
  J out(rapidjson::kObjectType), geometry(rapidjson::kObjectType), uv(rapidjson::kArrayType), wires(rapidjson::kArrayType);
  out.AddMember("index", index, a); out.AddMember("orientation", str(orientation(face.Orientation()), a), a);
  geometry.AddMember("type", str(surfaceNames[p.type], a), a);
  if (p.type <= GeomAbs_Torus) {
    geometry.AddMember("origin", point(p.axis.Location(), a), a);
    geometry.AddMember("axis", direction(p.axis.Direction(), a), a);
    gp_Ax3 frame;
    switch(p.type) {
      case GeomAbs_Plane:frame=s.Plane().Position();break;
      case GeomAbs_Cylinder:frame=s.Cylinder().Position();break;
      case GeomAbs_Cone:frame=s.Cone().Position();break;
      case GeomAbs_Sphere:frame=s.Sphere().Position();break;
      case GeomAbs_Torus:frame=s.Torus().Position();break;
      default:break;
    }
    geometry.AddMember("x_direction",direction(frame.XDirection(),a),a);
    geometry.AddMember("y_direction",direction(frame.YDirection(),a),a);
  }
  if (p.type != GeomAbs_Plane && p.type <= GeomAbs_Torus) geometry.AddMember("radius", num(p.radius), a);
  if (p.type == GeomAbs_Cone) geometry.AddMember("semi_angle_radians", num(p.angle), a);
  if (p.type == GeomAbs_Torus) geometry.AddMember("minor_radius", num(s.Torus().MinorRadius()), a);
  if (p.type == GeomAbs_Cylinder || p.type == GeomAbs_Cone) geometry.AddMember("inward_wall", inwardWall(face), a);
  out.AddMember("surface", geometry, a);
  for (double v : {s.FirstUParameter(), s.LastUParameter(), s.FirstVParameter(), s.LastVParameter()}) uv.PushBack(num(v), a);
  out.AddMember("uv_bounds", uv, a); out.AddMember("bbox", bounds(face, a), a);
  GProp_GProps props; BRepGProp::SurfaceProperties(face, props, false, false);
  out.AddMember("area", num(props.Mass()), a); out.AddMember("center", point(props.CentreOfMass(), a), a);
  out.AddMember("max_tolerance", num(maxTolerance(face)), a);
  auto outer = BRepTools::OuterWire(face);
  TopTools_IndexedMapOfShape wm; TopExp::MapShapes(face, TopAbs_WIRE, wm);
  for (int wi = 1; wi <= wm.Extent(); ++wi) {
    J wire(rapidjson::kObjectType), uses(rapidjson::kArrayType);
    wire.AddMember("outer", wm(wi).IsSame(outer), a);
    for (TopoDS_Iterator it(wm(wi)); it.More(); it.Next()) {
      if (it.Value().ShapeType() != TopAbs_EDGE) continue;
      auto edge = TopoDS::Edge(it.Value());
      J use(rapidjson::kObjectType);
      use.AddMember("edge_index", edgeMap.FindIndex(edge), a);
      use.AddMember("orientation", str(orientation(edge.Orientation()), a), a);
      use.AddMember("seam", bool(BRep_Tool::IsClosed(edge, face)), a);
      use.AddMember("degenerated", bool(BRep_Tool::Degenerated(edge)), a);
      uses.PushBack(use, a);
    }
    wire.AddMember("edge_uses", uses, a); wires.PushBack(wire, a);
  }
  out.AddMember("wires", wires, a);
  return out;
}
struct Patch {
  TopoDS_Shape root;
  TopTools_IndexedMapOfShape faces, edges;
  std::vector<std::set<int>> adjacent;
  std::vector<std::set<int>> edgeFaces;
  explicit Patch(const TopoDS_Shape& s) : root(s) {
    TopExp::MapShapes(s, TopAbs_FACE, faces); TopExp::MapShapes(s, TopAbs_EDGE, edges);
    adjacent.resize(faces.Extent()+1); edgeFaces.resize(edges.Extent()+1);
    TopTools_IndexedDataMapOfShapeListOfShape map;
    TopExp::MapShapesAndUniqueAncestors(s, TopAbs_EDGE, TopAbs_FACE, map);
    for (int e = 1; e <= edges.Extent(); ++e) {
      int mi = map.FindIndex(edges(e)); if (!mi) continue;
      for (TopTools_ListIteratorOfListOfShape it(map(mi)); it.More(); it.Next()) edgeFaces[e].insert(faces.FindIndex(it.Value()));
      for (int i : edgeFaces[e]) for (int j : edgeFaces[e]) if (i != j) adjacent[i].insert(j);
    }
  }
};
J surfaceInfo(const J& request, A& a) {
  auto name = field(request, "shape"); Patch p(shape(name));
  if (request.HasMember("expected_revision")) checkRevision(request, "expected_revision", p.root);
  std::set<int> ids;
  if (request.HasMember("faces")) {
    if(request.HasMember("offset")||request.HasMember("limit"))throw std::runtime_error("Use faces or pagination, not both");
    ids = faceIndices(request, p.faces.Extent());
  }
  else {
    int offset = integer(request, "offset", 0), limit = integer(request, "limit", 100);
    if (offset < 0 || limit < 1 || limit > 500) throw std::runtime_error("offset >= 0; 1 <= limit <= 500");
    for (int i = offset+1; i <= p.faces.Extent() && i <= offset+limit; ++i) ids.insert(i);
  }
  J out(rapidjson::kObjectType), items(rapidjson::kArrayType);
  for (int i : ids) items.PushBack(faceInfo(TopoDS::Face(p.faces(i)), i, p.edges, a), a);
  out.AddMember("shape", str(name, a), a); out.AddMember("revision", str(revision(p.root), a), a);
  out.AddMember("total", p.faces.Extent(), a); out.AddMember("items", items, a);
  out.AddMember("measurement_mode", "geometry_without_triangulation", a); return out;
}
J patchContext(const J& request, A& a) {
  Patch p(shape(field(request, "shape"))); checkRevision(request, "expected_revision", p.root);
  auto seeds = faceIndices(request, p.faces.Extent()), selected = seeds;
  int depth = integer(request, "depth", 1), maxFaces = integer(request, "max_faces", 100);
  if (depth < 0 || depth > 5 || maxFaces < static_cast<int>(seeds.size()) || maxFaces > 500) throw std::runtime_error("depth 0-5; seed count <= max_faces <= 500");
  auto front = seeds; bool truncated = false;
  for (int level = 0; level < depth; ++level) {
    std::set<int> next;
    for (int i : front) for (int j : p.adjacent[i]) if (!selected.count(j)) {
      if (selected.size() >= static_cast<size_t>(maxFaces)) { truncated = true; continue; }
      selected.insert(j); next.insert(j);
    }
    front = next;
  }
  J out(rapidjson::kObjectType), faces(rapidjson::kArrayType), links(rapidjson::kArrayType);
  for (int i : selected) faces.PushBack(faceInfo(TopoDS::Face(p.faces(i)), i, p.edges, a), a);
  for (int e = 1; e <= p.edges.Extent(); ++e) {
    bool relevant = false; for (int i : p.edgeFaces[e]) relevant |= selected.count(i) != 0;
    if (!relevant) continue;
    J link(rapidjson::kObjectType); link.AddMember("edge_index", e, a); link.AddMember("faces", integers(p.edgeFaces[e], a), a);
    J relations(rapidjson::kArrayType);
    for(int i:p.edgeFaces[e])for(int j:p.edgeFaces[e])if(j>i) {
      auto fi=TopoDS::Face(p.faces(i)),fj=TopoDS::Face(p.faces(j));auto si=support(fi),sj=support(fj);
      bool wi=si.type==GeomAbs_Cylinder||si.type==GeomAbs_Cone,wj=sj.type==GeomAbs_Cylinder||sj.type==GeomAbs_Cone;
      J relation(rapidjson::kObjectType);relation.AddMember("a",i,a);relation.AddMember("b",j,a);
      relation.AddMember("coaxial_walls",wi&&wj&&coaxial(si.axis,sj.axis),a);
      relation.AddMember("same_analytic_support",si.type<=GeomAbs_Torus&&sj.type<=GeomAbs_Torus?J(sameSupport(fi,fj,1e-6)):J(),a);
      relations.PushBack(relation,a);
    }
    link.AddMember("relations",relations,a);
    link.AddMember("length", num(length(p.edges(e))), a); links.PushBack(link, a);
  }
  out.AddMember("revision", str(revision(p.root), a), a); out.AddMember("seed_faces", integers(seeds, a), a);
  out.AddMember("faces", faces, a); out.AddMember("edge_faces", links, a); out.AddMember("truncated", truncated, a);
  out.AddMember("id_scope", "Indices belong to this revision; seam edge uses are retained in each face's wires", a); return out;
}

struct ProfileSegment { double low, high, slope, intercept; };
struct HoleFeature {
  std::set<int> seeds, expanded, boundary;
  std::map<int, std::string> reasons;
  gp_Ax1 axis;
  std::vector<ProfileSegment> profile;
  bool supported = false;
  std::string reason;
};
HoleFeature recognizeHole(const Patch& p, const std::set<int>& seeds, double tol) {
  HoleFeature h; h.seeds = seeds;
  int firstWall=0;for(int i:seeds)if(inwardWall(TopoDS::Face(p.faces(i)))){firstWall=i;break;}
  if (!firstWall) { h.reason = "Seeds must include an inward analytic cylinder/cone wall"; return h; }
  auto first = TopoDS::Face(p.faces(firstWall)); auto ref = support(first);
  h.axis = ref.axis;
  std::set<int> walls, ledges;
  for (int i = 1; i <= p.faces.Extent(); ++i) {
    auto face = TopoDS::Face(p.faces(i)); auto sp = support(face);
    if (inwardWall(face) && coaxial(h.axis, sp.axis, tol)) walls.insert(i);
  }
  for (int i = 1; i <= p.faces.Extent(); ++i) {
    auto sp = support(TopoDS::Face(p.faces(i)));
    if (sp.type != GeomAbs_Plane || !sp.axis.Direction().IsParallel(h.axis.Direction(), 1e-7) || p.adjacent[i].size() < 2) continue;
    bool allWalls = true; std::vector<double> radii;
    for (int j : p.adjacent[i]) {
      if (!walls.count(j)) { allWalls = false; break; }
      auto other = support(TopoDS::Face(p.faces(j)));
      // Radius at the ledge's axial coordinate, for either axis direction.
      radii.push_back(other.radius + (other.type == GeomAbs_Cone ?
        gp_Vec(other.axis.Location(), sp.axis.Location()).Dot(gp_Vec(other.axis.Direction())) * std::tan(other.angle) : 0));
    }
    if (allWalls && *std::max_element(radii.begin(),radii.end())-*std::min_element(radii.begin(),radii.end()) > tol) ledges.insert(i);
  }
  for (int i : seeds) if (!walls.count(i)&&!ledges.count(i)) { h.reason = "Seeds do not belong to one coaxial inward feature"; return h; }
  h.expanded.insert(*seeds.begin()); std::vector<int> queue{*seeds.begin()};
  for (size_t q = 0; q < queue.size(); ++q) for (int j : p.adjacent[queue[q]])
    if ((walls.count(j) || ledges.count(j)) && h.expanded.insert(j).second) queue.push_back(j);
  for (int i : seeds) if (!h.expanded.count(i)) { h.reason = "Seeds are disconnected along the recognized feature"; return h; }
  for (int i : h.expanded) {
    h.reasons[i] = seeds.count(i) ? "user_seed" : ledges.count(i) ? "annular_bridge_between_coaxial_walls" : "adjacent_coaxial_inward_wall";
    for (int j : p.adjacent[i]) if (!h.expanded.count(j)) h.boundary.insert(j);
    if (!walls.count(i)) continue;
    BRepAdaptor_Surface s(TopoDS::Face(p.faces(i)));
    double u = (s.FirstUParameter()+s.LastUParameter())*.5;
    auto p0=s.Value(u,s.FirstVParameter()), p1=s.Value(u,s.LastVParameter());
    double t0=gp_Vec(h.axis.Location(),p0).Dot(gp_Vec(h.axis.Direction())), t1=gp_Vec(h.axis.Location(),p1).Dot(gp_Vec(h.axis.Direction()));
    double r0=gp_Lin(h.axis).Distance(p0), r1=gp_Lin(h.axis).Distance(p1);
    if (!std::isfinite(t0) || !std::isfinite(t1) || std::abs(t1-t0)<tol) { h.reason="Unbounded or degenerate axial wall"; return h; }
    double slope=(r1-r0)/(t1-t0), intercept=r0-slope*t0;
    ProfileSegment seg{std::min(t0,t1),std::max(t0,t1),slope,intercept};
    bool merged=false;
    for (auto& old : h.profile) if (std::abs(old.slope-slope)<1e-7 && std::abs(old.intercept-intercept)<tol && seg.low<=old.high+tol && seg.high>=old.low-tol) {
      old.low=std::min(old.low,seg.low); old.high=std::max(old.high,seg.high); merged=true; break;
    }
    if (!merged) h.profile.push_back(seg);
  }
  std::sort(h.profile.begin(),h.profile.end(),[](const auto& x,const auto& y){return x.low<y.low;});
  for (size_t i=1;i<h.profile.size();++i) {
    if (std::abs(h.profile[i-1].high-h.profile[i].low)>tol*10) {h.reason="Axial gaps or overlapping support profiles require another strategy";return h;}
    double join=(h.profile[i-1].high+h.profile[i].low)*.5; h.profile[i-1].high=h.profile[i].low=join;
  }
  if (h.profile.empty() || std::abs(h.profile.front().slope)>1e-7 || std::abs(h.profile.back().slope)>1e-7) {
    h.reason="Current recipe requires cylindrical terminal walls"; return h;
  }
  h.supported=true; h.reason="Coaxial piecewise-linear bore profile; zero-displacement calibration is required before editing"; return h;
}
J holeInfo(const Patch& p, const HoleFeature& h, A& a) {
  J out(rapidjson::kObjectType), reasons(rapidjson::kArrayType), segments(rapidjson::kArrayType), probes(rapidjson::kArrayType);
  out.AddMember("supported", h.supported, a); out.AddMember("reason", str(h.reason,a),a);
  out.AddMember("seed_faces",integers(h.seeds,a),a); out.AddMember("expanded_faces",integers(h.expanded,a),a); out.AddMember("boundary_faces",integers(h.boundary,a),a);
  for (const auto& entry:h.reasons) {J v(rapidjson::kObjectType);v.AddMember("face",entry.first,a);v.AddMember("reason",str(entry.second,a),a);reasons.PushBack(v,a);}
  out.AddMember("reasons",reasons,a);
  if (!h.supported) return out;
  out.AddMember("axis_origin",point(h.axis.Location(),a),a);out.AddMember("axis_direction",direction(h.axis.Direction(),a),a);
  Bnd_Box box; BRepBndLib::AddOptimal(p.root,box,false,false);
  double x0,y0,z0,x1,y1,z1;box.Get(x0,y0,z0,x1,y1,z1);
  double low=1e100,high=-1e100;
  for(double x:{x0,x1})for(double y:{y0,y1})for(double z:{z0,z1}) {
    double t=gp_Vec(h.axis.Location(),gp_Pnt(x,y,z)).Dot(gp_Vec(h.axis.Direction())); low=std::min(low,t);high=std::max(high,t);
  }
  double pad=std::max(1.0,(high-low)*.01);
  for (size_t i=0;i<h.profile.size();++i) {
    const auto& seg=h.profile[i]; double start=i==0?low-pad:seg.low,end=i+1==h.profile.size()?high+pad:seg.high;
    J v(rapidjson::kObjectType);v.AddMember("origin",point(h.axis.Location().Translated(gp_Vec(h.axis.Direction())*start),a),a);
    v.AddMember("axis",direction(h.axis.Direction(),a),a);v.AddMember("length",num(end-start),a);
    v.AddMember("radius_start",num(seg.slope*start+seg.intercept),a);v.AddMember("radius_end",num(seg.slope*end+seg.intercept),a);segments.PushBack(v,a);
    // Core samples are anchored at internal transitions, not old exterior exits.
    std::vector<double> stations;
    double epsilon=std::min(.001,(seg.high-seg.low)*.01);
    if(i>0)stations.push_back(seg.low+epsilon);
    if(i+1<h.profile.size())stations.push_back(seg.high-epsilon);
    if(std::abs(seg.slope)>1e-7 || h.profile.size()==1)stations.push_back((seg.low+seg.high)*.5);
    for(double t:stations) {
      J probe(rapidjson::kObjectType);probe.AddMember("center",point(h.axis.Location().Translated(gp_Vec(h.axis.Direction())*t),a),a);
      probe.AddMember("axis",direction(h.axis.Direction(),a),a);probe.AddMember("radius",num(seg.slope*t+seg.intercept),a);probes.PushBack(probe,a);
    }
  }
  out.AddMember("tool_segments",segments,a);out.AddMember("core_sections",probes,a);
  out.AddMember("scope","Analytic inward coaxial walls and annular bridges only; expansion is a proposal, not proof of a complete feature",a);return out;
}
TopoDS_Shape commonShape(const TopoDS_Shape&,const TopoDS_Shape&);
TopoDS_Shape boreTool(const HoleFeature&,const gp_Vec&,const TopoDS_Shape&);
J sectionEvidence(const TopoDS_Shape&,const J&,const gp_Vec&,double,bool&,A&);
J materialIntersection(const TopoDS_Shape& s,A& a) {
  GProp_GProps mass;BRepGProp::VolumeProperties(s,mass,true,false,false);
  J result(rapidjson::kObjectType);result.AddMember("solid_count",count(s,TopAbs_SOLID),a);
  result.AddMember("volume",num(mass.Mass()),a);result.AddMember("empty_material",count(s,TopAbs_SOLID)==0,a);return result;
}
J expandSelection(const J& request,A& a) {
  Patch p(shape(field(request,"shape")));checkRevision(request,"expected_revision",p.root);
  double tol=real(request,"linear_tolerance",1e-6);if(tol<=0||tol>.01)throw std::runtime_error("linear_tolerance must be in (0,.01]");
  auto feature=recognizeHole(p,faceIndices(request,p.faces.Extent()),tol);
  auto result=holeInfo(p,feature,a);
  if(feature.supported) {
    auto material=commonShape(p.root,boreTool(feature,gp_Vec(0,0,0),p.root));
    auto evidence=materialIntersection(material,a);
    if(!evidence["empty_material"].GetBool()) {
      result["supported"].SetBool(false);
      result["reason"]=str("The inferred full bore envelope intersects source material; selected walls are not a complete empty coaxial bore",a);
    }
    result.AddMember("source_void_check",evidence,a);
    TopoDS_Compound boundary;BRep_Builder builder;builder.MakeCompound(boundary);
    for(int i=1;i<=p.faces.Extent();++i)builder.Add(boundary,p.faces(i));
    bool closed=true;auto sections=sectionEvidence(boundary,result,gp_Vec(0,0,0),1e-5,closed,a);
    result.AddMember("source_core_sections",sections,a);
    if(!closed) {
      result["supported"].SetBool(false);
      result["reason"]=str("Source core sections are partial/open sectors; the complete coaxial through-bore recipe is not applicable",a);
    }
  }
  result.AddMember("revision",str(revision(p.root),a),a);result.AddMember("strategy","coaxial_hole",a);return result;
}

TopoDS_Shape commonShape(const TopoDS_Shape& a,const TopoDS_Shape& b) {
  BRepAlgoAPI_Common op;TopTools_ListOfShape args,tools;args.Append(a);tools.Append(b);
  op.SetArguments(args);op.SetTools(tools);op.SetNonDestructive(true);op.Build();
  if(!op.IsDone()||op.HasErrors()||op.Shape().IsNull())throw std::runtime_error("Intersection measurement failed");return op.Shape();
}
template<class Operation>TopoDS_Shape booleanShape(const TopoDS_Shape& a,const TopoDS_Shape& b) {
  Operation op;TopTools_ListOfShape args,tools;args.Append(a);tools.Append(b);
  op.SetArguments(args);op.SetTools(tools);op.SetNonDestructive(true);op.Build();
  if(!op.IsDone()||op.HasErrors()||op.Shape().IsNull())throw std::runtime_error("Validation Boolean failed");return op.Shape();
}
TopoDS_Shape boreTool(const HoleFeature& h,const gp_Vec& delta,const TopoDS_Shape& envelope) {
  auto origin=h.axis.Location().Translated(delta);auto axis=h.axis.Direction();
  Bnd_Box box;BRepBndLib::AddOptimal(envelope,box,false,false);
  if(box.IsVoid()||box.IsOpen())throw std::runtime_error("Finite validation bounds required");
  double x0,y0,z0,x1,y1,z1;box.Get(x0,y0,z0,x1,y1,z1);
  double low=1e100,high=-1e100;
  for(double x:{x0,x1})for(double y:{y0,y1})for(double z:{z0,z1}) {
    double t=gp_Vec(origin,gp_Pnt(x,y,z)).Dot(gp_Vec(axis));low=std::min(low,t);high=std::max(high,t);
  }
  double pad=std::max(1.0,(high-low)*.01);TopoDS_Shape result;
  for(size_t i=0;i<h.profile.size();++i) {
    const auto& s=h.profile[i];double start=i==0?std::min(s.low,low-pad):s.low,end=i+1==h.profile.size()?std::max(s.high,high+pad):s.high;
    double r0=s.slope*start+s.intercept,r1=s.slope*end+s.intercept;
    if(!std::isfinite(r0)||!std::isfinite(r1)||!std::isfinite(end-start)||std::min(r0,r1)<=0||end<=start)throw std::runtime_error("Invalid analytic bore envelope");
    gp_Ax2 frame(origin.Translated(gp_Vec(axis)*start),axis);
    TopoDS_Shape piece=std::abs(r1-r0)<1e-10?BRepPrimAPI_MakeCylinder(frame,r0,end-start).Shape():BRepPrimAPI_MakeCone(frame,r0,r1,end-start).Shape();
    result=result.IsNull()?piece:booleanShape<BRepAlgoAPI_Fuse>(result,piece);
  }
  return result;
}
J sectionEvidence(const TopoDS_Shape& boundary,const J& info,const gp_Vec& delta,double tolerance,bool& complete,A& a) {
  J probes(rapidjson::kArrayType);
  for(const auto& sample:info["core_sections"].GetArray()) {
    const auto& c=sample["center"];const auto& ax=sample["axis"];double radius=sample["radius"].GetDouble();
    gp_Pnt center(c[0].GetDouble()+delta.X(),c[1].GetDouble()+delta.Y(),c[2].GetDouble()+delta.Z());
    auto ring=BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(center,gp_Dir(ax[0].GetDouble(),ax[1].GetDouble(),ax[2].GetDouble())),radius)).Edge();
    double fraction=length(commonShape(boundary,ring))/(2*std::acos(-1.0)*radius);
    bool retained=std::abs(fraction-1)<=tolerance;complete&=retained;
    J v(rapidjson::kObjectType);v.AddMember("center",point(center,a),a);v.AddMember("radius",num(radius),a);
    v.AddMember("retained_fraction",num(fraction),a);v.AddMember("complete",retained,a);probes.PushBack(v,a);
  }
  return probes;
}
gp_Vec vector3(const J& request,const char* key) {
  if(!request.HasMember(key)||!request[key].IsArray()||request[key].Size()!=3)throw std::runtime_error("vector must have exactly three finite numbers");
  for(const auto& v:request[key].GetArray())if(!v.IsNumber()||!std::isfinite(v.GetDouble())||std::abs(v.GetDouble())>1e9)throw std::runtime_error("vector must have exactly three finite numbers of magnitude <= 1e9");
  return gp_Vec(request[key][0].GetDouble(),request[key][1].GetDouble(),request[key][2].GetDouble());
}
bool singleSolidOnly(const TopoDS_Shape& s) {
  TopTools_IndexedMapOfShape solids;TopExp::MapShapes(s,TopAbs_SOLID,solids);
  if(solids.Extent()!=1)return false;
  int solidUses=0;for(TopExp_Explorer it(s,TopAbs_SOLID);it.More();it.Next())++solidUses;
  if(solidUses!=1)return false;
  for(auto type:{TopAbs_FACE,TopAbs_EDGE,TopAbs_VERTEX}) {
    if(count(s,type)!=count(solids(1),type))return false;
    int rootUses=0,bodyUses=0;
    for(TopExp_Explorer it(s,type);it.More();it.Next())++rootUses;
    for(TopExp_Explorer it(solids(1),type);it.More();it.Next())++bodyUses;
    if(rootUses!=bodyUses)return false;
  }
  return true;
}
J validateEdit(const J& request,A& a) {
  Patch original(shape(field(request,"source"))),candidate(shape(field(request,"candidate")));
  checkRevision(request,"source_revision",original.root);checkRevision(request,"candidate_revision",candidate.root);
  const auto ids=faceIndices(request,original.faces.Extent());auto delta=vector3(request,"vector");
  if(!request.HasMember("policy")||!request["policy"].IsObject())throw std::runtime_error("Explicit edit policy is required");
  const auto& policy=request["policy"];auto mode=field(policy,"target_mode");
  const std::set<std::string> policyKeys={"target_mode","allow_breakthrough","allow_new_supports","require_exact","linear_tolerance","area_relative_tolerance","max_tolerance_growth","relative_volume_tolerance"};
  for(auto it=policy.MemberBegin();it!=policy.MemberEnd();++it)if(!policyKeys.count(it->name.GetString()))throw std::runtime_error("Unknown edit policy field");
  if(mode!="trimmed_patch"&&mode!="support_geometry")throw std::runtime_error("target_mode must be trimmed_patch or support_geometry");
  for(auto key:{"allow_breakthrough","allow_new_supports"})if(!policy.HasMember(key))throw std::runtime_error(std::string("Missing policy field: ")+key);
  bool allowBreak=flag(policy,"allow_breakthrough"),allowNew=flag(policy,"allow_new_supports"),requireExact=flag(policy,"require_exact");
  double linearTol=real(policy,"linear_tolerance",1e-6),areaTol=real(policy,"area_relative_tolerance",1e-5),growth=real(policy,"max_tolerance_growth",1e-5);
  if(linearTol<=0||linearTol>.01||areaTol<=0||areaTol>.1||growth<0||growth>.01)throw std::runtime_error("Policy tolerance out of range");
  BRepCheck_Analyzer sourceCheck(original.root),candidateCheck(candidate.root);
  GProp_GProps candidateVolume;BRepGProp::VolumeProperties(candidate.root,candidateVolume,true,false,false);
  bool valid=sourceCheck.IsValid()&&singleSolidOnly(original.root)&&candidateCheck.IsValid()&&singleSolidOnly(candidate.root)&&std::isfinite(candidateVolume.Mass())&&candidateVolume.Mass()>0;
  if(!valid) {
    J result(rapidjson::kObjectType),checks(rapidjson::kObjectType);
    checks.AddMember("ordinary_valid_single_solid",false,a);
    checks.AddMember("single_solid_without_free_or_duplicate_uses",singleSolidOnly(candidate.root),a);
    checks.AddMember("positive_finite_volume",std::isfinite(candidateVolume.Mass())&&candidateVolume.Mass()>0,a);
    result.AddMember("accepted",false,a);result.AddMember("status","invalid_source_or_candidate",a);result.AddMember("checks",checks,a);return result;
  }
  TopoDS_Compound boundary;BRep_Builder builder;builder.MakeCompound(boundary);
  for(int j=1;j<=candidate.faces.Extent();++j)builder.Add(boundary,candidate.faces(j));
  gp_Trsf move;move.SetTranslation(delta);
  std::vector<TopoDS_Face> targets(original.faces.Extent()+1);
  std::map<int,std::set<int>> mapped;
  J coverage(rapidjson::kArrayType);bool full=true,located=true;
  for(int i:ids) {
    targets[i]=TopoDS::Face(BRepBuilderAPI_Transform(original.faces(i),move,true).Shape());
    double expected=area(targets[i]),retained=area(commonShape(boundary,targets[i]));
    bool complete=expected>0&&std::abs(retained-expected)<=expected*areaTol;full&=complete;
    for(int j=1;j<=candidate.faces.Extent();++j)if(sameSupport(targets[i],TopoDS::Face(candidate.faces(j)),linearTol)) {
      // A planar support is infinite: require overlap with the finite target ledge.
      if(support(targets[i]).type==GeomAbs_Plane&&area(commonShape(targets[i],candidate.faces(j)))<=linearTol*linearTol)continue;
      mapped[i].insert(j);
    }
    located&=!mapped[i].empty();
    J v(rapidjson::kObjectType);v.AddMember("source_face",i,a);v.AddMember("target_area",num(expected),a);v.AddMember("retained_area",num(retained),a);
    v.AddMember("retained_fraction",expected>0?num(retained/expected):J(),a);v.AddMember("full_patch_retained",complete,a);
    v.AddMember("candidate_faces",integers(mapped[i],a),a);coverage.PushBack(v,a);
  }
  bool connected=true;J links(rapidjson::kArrayType);
  for(int i:ids)for(int j:original.adjacent[i])if(j>i&&ids.count(j)) {
    bool found=false;
    for(int x:mapped[i])for(int y:mapped[j])found|=x==y||candidate.adjacent[x].count(y)!=0;
    connected&=found;J v(rapidjson::kObjectType);v.AddMember("source_a",i,a);v.AddMember("source_b",j,a);v.AddMember("retained",found,a);links.PushBack(v,a);
  }
  auto feature=recognizeHole(original,ids,linearTol);
  bool featureScope=feature.supported&&feature.expanded==ids;
  J movedVoid(rapidjson::kObjectType),sourceVoid(rapidjson::kObjectType),locality(rapidjson::kObjectType);
  bool voidEmpty=false,localityOK=false;
  if(featureScope) {
    TopoDS_Compound envelope;builder.MakeCompound(envelope);builder.Add(envelope,original.root);builder.Add(envelope,candidate.root);
    auto oldTool=boreTool(feature,gp_Vec(0,0,0),envelope),movedTool=boreTool(feature,delta,envelope);
    sourceVoid=materialIntersection(commonShape(original.root,oldTool),a);
    if(!sourceVoid["empty_material"].GetBool())featureScope=false;
    else {
      movedVoid=materialIntersection(commonShape(candidate.root,movedTool),a);
      voidEmpty=movedVoid["empty_material"].GetBool();
      auto influence=booleanShape<BRepAlgoAPI_Fuse>(oldTool,movedTool);
      TopoDS_Compound beforeBoundary;builder.MakeCompound(beforeBoundary);
      for(int i=1;i<=original.faces.Extent();++i)builder.Add(beforeBoundary,original.faces(i));
      auto beforeOutside=booleanShape<BRepAlgoAPI_Cut>(beforeBoundary,influence),afterOutside=booleanShape<BRepAlgoAPI_Cut>(boundary,influence);
      // Eliminate byte-identical finite faces first; whole-compound coincidence
      // checking is expensive on imported parts. Compare exact canonical bytes,
      // not the noncryptographic revision hash. Boolean-measure every remainder.
      TopTools_IndexedMapOfShape beforeFaces,afterFaces;
      TopExp::MapShapes(beforeOutside,TopAbs_FACE,beforeFaces);TopExp::MapShapes(afterOutside,TopAbs_FACE,afterFaces);
      std::map<std::string,std::vector<int>> byGeometry;
      for(int i=1;i<=beforeFaces.Extent();++i)byGeometry[canonicalBrep(beforeFaces(i))].push_back(i);
      std::set<int> paired;double sharedArea=0;int matchedFaces=0;
      TopoDS_Compound unmatchedBefore,unmatchedAfter;builder.MakeCompound(unmatchedBefore);builder.MakeCompound(unmatchedAfter);
      for(int j=1;j<=afterFaces.Extent();++j) {
        auto key=canonicalBrep(afterFaces(j));auto found=byGeometry.find(key);
        if(found!=byGeometry.end()&&!found->second.empty()) {
          int i=found->second.back();found->second.pop_back();paired.insert(i);sharedArea+=area(beforeFaces(i));++matchedFaces;
        }else builder.Add(unmatchedAfter,afterFaces(j));
      }
      for(int i=1;i<=beforeFaces.Extent();++i)if(!paired.count(i))builder.Add(unmatchedBefore,beforeFaces(i));
      if(count(unmatchedBefore,TopAbs_FACE)&&count(unmatchedAfter,TopAbs_FACE))sharedArea+=area(commonShape(unmatchedBefore,unmatchedAfter));
      double beforeArea=area(beforeOutside),afterArea=area(afterOutside);
      localityOK=std::abs(beforeArea-sharedArea)<=areaTol*std::max(beforeArea,linearTol*linearTol)&&
        std::abs(afterArea-sharedArea)<=areaTol*std::max(afterArea,linearTol*linearTol);
      locality.AddMember("source_boundary_area_outside_envelope",num(beforeArea),a);
      locality.AddMember("candidate_boundary_area_outside_envelope",num(afterArea),a);
      locality.AddMember("shared_boundary_area_outside_envelope",num(sharedArea),a);
      locality.AddMember("identical_finite_faces",matchedFaces,a);
      locality.AddMember("preserved",localityOK,a);
    }
  }
  J probes(rapidjson::kArrayType);bool coreComplete=featureScope;
  if(featureScope) {
    auto info=holeInfo(original,feature,a);
    // Translation along a single cylindrical support's own axis is a no-op
    // for support_geometry. Keep its diagnostic station within the stock.
    auto probeDelta=delta;
    if(feature.profile.size()==1)probeDelta-=gp_Vec(feature.axis.Direction())*delta.Dot(gp_Vec(feature.axis.Direction()));
    probes=sectionEvidence(boundary,info,probeDelta,areaTol,coreComplete,a);
    // Full annular ledges are an additional check against transition breakout.
    for(int i:ids)if(support(TopoDS::Face(original.faces(i))).type==GeomAbs_Plane) {
      double expected=area(targets[i]),got=area(commonShape(boundary,targets[i]));coreComplete&=expected>0&&std::abs(got-expected)<=areaTol*expected;
    }
  }
  std::set<int> newSupports;
  std::map<int,TopoDS_Face> naturalSupports;
  for(int j=1;j<=candidate.faces.Extent();++j) {
    bool known=false;
    for(int i=1;i<=original.faces.Extent();++i) {
      if(sameSupport(ids.count(i)?targets[i]:TopoDS::Face(original.faces(i)),TopoDS::Face(candidate.faces(j)),linearTol)){known=true;break;}
    }
    if(!known) {
      auto target=TopoDS::Face(candidate.faces(j));auto type=support(target).type;
      if(type==GeomAbs_BSplineSurface||type==GeomAbs_BezierSurface)for(int i=1;i<=original.faces.Extent();++i) {
        if(ids.count(i)||support(TopoDS::Face(original.faces(i))).type!=type)continue;
        // Filled holes can add a newly parameterized patch on an existing
        // exterior spline support. Test the WHOLE candidate patch against the
        // untrimmed original support, rather than a few coincident sample points.
        try {
          if(!naturalSupports.count(i)) {
            auto g=BRep_Tool::Surface(TopoDS::Face(original.faces(i)));
            naturalSupports[i]=BRepBuilderAPI_MakeFace(g,linearTol).Face();
          }
          double expected=area(target),overlap=area(commonShape(target,naturalSupports[i]));
          if(expected>0&&std::abs(overlap-expected)<=expected*areaTol){known=true;break;}
        }catch(const Standard_Failure&){/* Conservative: keep this support unclassified. */}
         catch(const std::runtime_error&){/* Intersection failure is not evidence of equality. */}
      }
    }
    if(!known)newSupports.insert(j);
  }
  // Exactness must be selected BEFORE Init performs edge checks. Setting the
  // flag after construction does not recompute cached check results in 7.7.
  BRepCheck_Analyzer sourceExact(original.root,true,false,true),candidateExact(candidate.root,true,false,true);
  bool exact=candidateExact.IsValid(),sourceExactValid=sourceExact.IsValid();
  double beforeTolerance=maxTolerance(original.root),afterTolerance=maxTolerance(candidate.root);
  bool toleranceOK=afterTolerance<=beforeTolerance+growth;
  bool passed=valid&&located&&connected&&(mode=="support_geometry"||full)&&featureScope&&voidEmpty&&localityOK&&(allowBreak||coreComplete)&&(allowNew||newSupports.empty())&&(!requireExact||exact)&&toleranceOK;
  J out(rapidjson::kObjectType),checks(rapidjson::kObjectType);
  checks.AddMember("ordinary_valid_single_solid",valid,a);checks.AddMember("target_supports_located",located,a);checks.AddMember("internal_adjacency_retained",connected,a);
  checks.AddMember("single_solid_without_free_or_duplicate_uses",singleSolidOnly(candidate.root),a);
  checks.AddMember("positive_finite_volume",std::isfinite(candidateVolume.Mass())&&candidateVolume.Mass()>0,a);
  checks.AddMember("full_trimmed_patch_retained",full,a);checks.AddMember("breakthrough_check_available",featureScope,a);checks.AddMember("core_transition_sections_complete",coreComplete,a);
  checks.AddMember("entire_moved_bore_void",voidEmpty,a);checks.AddMember("outside_feature_envelope_preserved",localityOK,a);
  checks.AddMember("new_supports_allowed_or_absent",allowNew||newSupports.empty(),a);checks.AddMember("tolerance_growth_allowed",toleranceOK,a);
  out.AddMember("accepted",passed,a);out.AddMember("status",str(passed?"policy_checks_passed":(!featureScope?"inconclusive":"policy_checks_failed"),a),a);
  out.AddMember("source_revision",str(revision(original.root),a),a);out.AddMember("candidate_revision",str(revision(candidate.root),a),a);
  out.AddMember("checks",checks,a);out.AddMember("target_coverage",coverage,a);out.AddMember("adjacency",links,a);out.AddMember("core_sections",probes,a);
  out.AddMember("source_void",sourceVoid,a);out.AddMember("moved_void",movedVoid,a);out.AddMember("change_locality",locality,a);
  out.AddMember("unclassified_candidate_supports",integers(newSupports,a),a);
  out.AddMember("general_support_mapping","Exact world-space serialization, or full candidate area intersection with an untrimmed original spline support at kernel tolerances",a);
  out.AddMember("source_exact_valid",sourceExactValid,a);out.AddMember("candidate_exact_valid",exact,a);
  out.AddMember("source_max_tolerance",num(beforeTolerance),a);out.AddMember("candidate_max_tolerance",num(afterTolerance),a);
  out.AddMember("scope","Declared checks only. Core circles sample internal transitions; they do not certify an entire bore or global design intent. Unclassified general surfaces are conservative failures when new supports are forbidden.",a);
  return out;
}
